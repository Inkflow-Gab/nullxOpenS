// Package agent runs the model conversation and executes tool calls.
package agent

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"strings"

	"github.com/Inkflow-Gab/nullxOpenS/internal/config"
	"github.com/Inkflow-Gab/nullxOpenS/internal/llm"
	"github.com/Inkflow-Gab/nullxOpenS/internal/session"
	"github.com/Inkflow-Gab/nullxOpenS/internal/tools"
	"github.com/Inkflow-Gab/nullxOpenS/internal/ui"
)

// toolAliases maps the official OpenCode tool names (and common variants) to
// the matching built-in tool, so free-tier sessions keep working when the
// gateway's shaping makes the model call an official name.
var toolAliases = map[string]string{
	"bash":     "bash",
	"shell":    "bash",
	"terminal": "bash",
	"read":     "read",
	"view":     "read",
	"cat":      "read",
	"write":    "write",
	"create":   "write",
	"edit":     "edit",
	"patch":    "edit",
	"replace":  "edit",
	"glob":     "glob",
	"find":     "glob",
	"grep":     "grep",
	"search":   "grep",
	"ls":       "ls",
	"list":     "ls",
}

// Agent owns one conversation.
type Agent struct {
	Config  config.Config
	Client  *llm.Client
	Tools   *tools.Registry
	UI      *ui.UI
	Session *session.Session
	history []llm.Message
}

// New builds an agent, restoring history from sess when it is non-nil.
func New(cfg config.Config, client *llm.Client, registry *tools.Registry, screen *ui.UI, sess *session.Session) *Agent {
	runner := &Agent{Config: cfg, Client: client, Tools: registry, UI: screen, Session: sess}
	if sess != nil {
		runner.history = append([]llm.Message(nil), sess.Messages...)
	}
	return runner
}

// Reset clears the conversation and the saved session.
func (a *Agent) Reset() {
	a.history = nil
	if a.Session != nil {
		a.Session.Messages = nil
		_ = a.Session.Save()
	}
}

// Run sends input to the model and executes tool calls until the model
// produces a final answer or max_steps is reached.
func (a *Agent) Run(ctx context.Context, input string) error {
	cwd, _ := os.Getwd()
	if len(a.history) == 0 {
		a.history = append(a.history, llm.Message{Role: "system", Content: systemPrompt(a.Config, cwd)})
	}
	a.history = append(a.history, llm.Message{Role: "user", Content: input})
	a.persist()

	for step := 0; step < a.Config.MaxSteps; step++ {
		request := llm.ChatRequest{
			Model:       a.Config.Model,
			Messages:    a.history,
			Tools:       a.Tools.Schemas(),
			MaxTokens:   a.Config.MaxTokens,
			Temperature: a.Config.Temperature,
		}
		result, err := a.stream(ctx, request)
		if err != nil {
			return err
		}
		a.UI.Newline()
		message := result.Message
		if message.Role == "" {
			message.Role = "assistant"
		}
		a.history = append(a.history, message)
		a.persist()
		if len(message.ToolCalls) == 0 {
			return nil
		}
		for _, call := range message.ToolCalls {
			output := a.runTool(ctx, call)
			a.history = append(a.history, llm.Message{
				Role:       "tool",
				ToolCallID: call.ID,
				Content:    output,
			})
			a.persist()
		}
	}
	return fmt.Errorf("stopped after %d steps without a final answer", a.Config.MaxSteps)
}

// stream sends the request and, when the gateway rejects the model itself,
// refreshes the catalog and retries once with the first free model. This keeps
// a stale or paid model ID from breaking a free-tier session.
func (a *Agent) stream(ctx context.Context, request llm.ChatRequest) (llm.Result, error) {
	result, err := a.Client.Stream(ctx, request, func(delta string) {
		a.UI.Stream(delta)
	})
	if err == nil || !isModelError(err) {
		return result, err
	}
	models, listErr := a.Client.Models(ctx)
	if listErr != nil {
		return result, err
	}
	chosen, ok := llm.ResolveModel(models, "auto")
	if !ok || chosen.ID == request.Model {
		return result, err
	}
	a.UI.Printf("\nmodel %q is unavailable; retrying with %q", request.Model, chosen.ID)
	a.Config.Model = chosen.ID
	request.Model = chosen.ID
	return a.Client.Stream(ctx, request, func(delta string) {
		a.UI.Stream(delta)
	})
}

func isModelError(err error) bool {
	text := strings.ToLower(err.Error())
	for _, marker := range []string{"404", "model_not_found", "was not found", "not available"} {
		if strings.Contains(text, marker) {
			return true
		}
	}
	return false
}

func (a *Agent) runTool(ctx context.Context, call llm.ToolCall) string {
	tool, ok := a.Tools.Get(call.Function.Name)
	if !ok {
		if target, exists := toolAliases[strings.ToLower(call.Function.Name)]; exists {
			tool, ok = a.Tools.Get(target)
		}
	}
	if !ok {
		return fmt.Sprintf("error: unknown tool %q; available tools are read, write, edit, ls, bash, glob, grep", call.Function.Name)
	}
	args := json.RawMessage(call.Function.Arguments)
	if len(args) == 0 {
		args = json.RawMessage("{}")
	}
	a.UI.ToolStart(tool.Name, call.Function.Arguments)
	if !a.authorize(tool.Name, call.Function.Arguments) {
		a.UI.ToolResult(tool.Name, "denied by permission policy")
		return "error: tool execution denied by permission policy"
	}
	output, err := tool.Run(ctx, args)
	if err != nil {
		output = "error: " + err.Error()
	}
	a.UI.ToolResult(tool.Name, output)
	return output
}

func (a *Agent) authorize(name, arguments string) bool {
	switch a.Config.Permission {
	case config.PermissionAllow:
		return true
	case config.PermissionDeny:
		return false
	}
	if !a.UI.Interactive() {
		return false
	}
	question := fmt.Sprintf("Allow tool %s? %s", name, truncate(arguments, 200))
	return a.UI.Ask(question)
}

func (a *Agent) persist() {
	if a.Session == nil {
		return
	}
	a.Session.Messages = append([]llm.Message(nil), a.history...)
	if err := a.Session.Save(); err != nil {
		a.UI.Printf("warning: session save failed: %v", err)
	}
}

func truncate(value string, limit int) string {
	value = strings.ReplaceAll(value, "\n", " ")
	if len(value) <= limit {
		return value
	}
	return value[:limit] + "..."
}
