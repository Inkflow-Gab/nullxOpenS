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
	UI      ui.Sink
	Session *session.Session
	history []llm.Message
	redo    []llm.Message
}

// New builds an agent, restoring history from sess when it is non-nil.
func New(cfg config.Config, client *llm.Client, registry *tools.Registry, screen ui.Sink, sess *session.Session) *Agent {
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
	a.redo = nil
	a.persist()

	for step := 0; step < a.Config.MaxSteps; step++ {
		request := llm.ChatRequest{
			Model:           a.Config.Model,
			Messages:        a.history,
			Tools:           a.Tools.Schemas(),
			MaxTokens:       a.Config.MaxTokens,
			Temperature:     a.Config.Temperature,
			ReasoningEffort: reasoningEffort(a.Config.ReasoningEffort),
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
	send := func(req llm.ChatRequest) (llm.Result, error) {
		result, err := a.Client.Stream(ctx, req,
			func(delta string) { a.UI.Stream(delta) },
			func(delta string) { a.UI.Reasoning(delta) },
		)
		if err == nil {
			a.reportBilling(result.Usage)
		}
		return result, err
	}
	result, err := send(request)
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
	return send(request)
}

func (a *Agent) reportBilling(usage llm.Usage) {
	source, cost, known := usage.Billing()
	if !known {
		return
	}
	free := strings.EqualFold(source, "free") || cost == 0
	a.UI.Billing(source, free, cost, true)
}

func reasoningEffort(value string) string {
	value = strings.TrimSpace(value)
	if strings.EqualFold(value, "none") {
		return ""
	}
	return value
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

// Compact replaces the conversation with a model-written summary, keeping the
// system prompt and a bounded history for the next turn.
func (a *Agent) Compact(ctx context.Context) (string, error) {
	if len(a.history) < 3 {
		return "", fmt.Errorf("not enough conversation to compact")
	}
	var transcript strings.Builder
	for _, message := range a.history {
		switch message.Role {
		case "system":
			continue
		case "tool":
			fmt.Fprintf(&transcript, "tool result: %s\n\n", clip(message.Content, 4000))
		case "assistant":
			if message.Content != "" {
				fmt.Fprintf(&transcript, "assistant: %s\n\n", clip(message.Content, 8000))
			}
			for _, call := range message.ToolCalls {
				fmt.Fprintf(&transcript, "assistant called %s(%s)\n", call.Function.Name, clip(call.Function.Arguments, 500))
			}
		default:
			fmt.Fprintf(&transcript, "%s: %s\n\n", message.Role, clip(message.Content, 8000))
		}
	}
	request := llm.ChatRequest{
		Model: a.Config.Model,
		Messages: []llm.Message{
			{Role: "system", Content: "Summarize the conversation. Keep decisions, file paths, commands, errors, and open tasks. Be concise but complete."},
			{Role: "user", Content: transcript.String()},
		},
		MaxTokens:       2048,
		Temperature:     0.2,
		ReasoningEffort: "low",
	}
	result, err := a.Client.Stream(ctx, request, nil, nil)
	if err != nil {
		return "", err
	}
	summary := strings.TrimSpace(result.Message.Content)
	if summary == "" {
		return "", fmt.Errorf("the model returned an empty summary")
	}
	cwd, _ := os.Getwd()
	a.history = []llm.Message{
		{Role: "system", Content: systemPrompt(a.Config, cwd)},
		{Role: "user", Content: "Conversation summary so far:\n\n" + summary},
		{Role: "assistant", Content: "Understood. I have the summary and will continue from it."},
	}
	a.redo = nil
	a.persist()
	return summary, nil
}

// Undo removes the last user turn and everything after it.
func (a *Agent) Undo() bool {
	for i := len(a.history) - 1; i >= 0; i-- {
		if a.history[i].Role != "user" {
			continue
		}
		a.redo = append([]llm.Message(nil), a.history[i:]...)
		a.history = a.history[:i]
		a.persist()
		return true
	}
	return false
}

// Redo restores the turn most recently removed by Undo.
func (a *Agent) Redo() bool {
	if len(a.redo) == 0 {
		return false
	}
	a.history = append(a.history, a.redo...)
	a.redo = nil
	a.persist()
	return true
}

// Export writes the conversation as Markdown.
func (a *Agent) Export(path string) error {
	var builder strings.Builder
	if a.Session != nil {
		fmt.Fprintf(&builder, "# nullx session %s\n\n", a.Session.ID)
	}
	for _, message := range a.history {
		switch message.Role {
		case "user":
			fmt.Fprintf(&builder, "## User\n\n%s\n\n", message.Content)
		case "assistant":
			if message.Content != "" {
				fmt.Fprintf(&builder, "## Assistant\n\n%s\n\n", message.Content)
			}
			for _, call := range message.ToolCalls {
				fmt.Fprintf(&builder, "**tool** `%s`\n\n```json\n%s\n```\n\n", call.Function.Name, call.Function.Arguments)
			}
		case "tool":
			fmt.Fprintf(&builder, "### Tool result\n\n```\n%s\n```\n\n", message.Content)
		}
	}
	return os.WriteFile(path, []byte(builder.String()), 0o644)
}

// HistoryCount reports how many messages the model will see next turn.
func (a *Agent) HistoryCount() int { return len(a.history) }

// History returns a copy of the current conversation.
func (a *Agent) History() []llm.Message {
	return append([]llm.Message(nil), a.history...)
}

func clip(value string, limit int) string {
	runes := []rune(value)
	if len(runes) <= limit {
		return value
	}
	return string(runes[:limit]) + "\n[truncated]"
}

func truncate(value string, limit int) string {
	value = strings.ReplaceAll(value, "\n", " ")
	if len(value) <= limit {
		return value
	}
	return value[:limit] + "..."
}
