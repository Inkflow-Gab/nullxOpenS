// Package llm is a minimal OpenAI-compatible chat client with streaming and
// tool-call support.
package llm

// Message is one entry of a chat conversation.
type Message struct {
	Role       string     `json:"role"`
	Content    string     `json:"content,omitempty"`
	ToolCalls  []ToolCall `json:"tool_calls,omitempty"`
	ToolCallID string     `json:"tool_call_id,omitempty"`
	Name       string     `json:"name,omitempty"`
}

// ToolCall is a model-requested function call.
type ToolCall struct {
	ID       string       `json:"id"`
	Type     string       `json:"type"`
	Function FunctionCall `json:"function"`
}

// FunctionCall is the name and raw JSON arguments of a tool call.
type FunctionCall struct {
	Name      string `json:"name"`
	Arguments string `json:"arguments"`
}

// Tool is a function schema advertised to the model.
type Tool struct {
	Type     string         `json:"type"`
	Function ToolDefinition `json:"function"`
}

// ToolDefinition describes one function.
type ToolDefinition struct {
	Name        string         `json:"name"`
	Description string         `json:"description"`
	Parameters  map[string]any `json:"parameters"`
}

// ChatRequest is the body of a chat completions request.
type ChatRequest struct {
	Model           string    `json:"model"`
	Messages        []Message `json:"messages"`
	Tools           []Tool    `json:"tools,omitempty"`
	Stream          bool      `json:"stream"`
	MaxTokens       int       `json:"max_tokens,omitempty"`
	Temperature     float64   `json:"temperature,omitempty"`
	ReasoningEffort string    `json:"reasoning_effort,omitempty"`
}

// OpenCodeUsage is the billing block opencode2api adds to a usage object.
type OpenCodeUsage struct {
	BillingSource string  `json:"billing_source"`
	ListCost      float64 `json:"list_cost"`
}

// Usage is the reported token usage of a response.
type Usage struct {
	PromptTokens     int            `json:"prompt_tokens"`
	CompletionTokens int            `json:"completion_tokens"`
	TotalTokens      int            `json:"total_tokens"`
	Cost             *float64       `json:"cost"`
	OpenCode         *OpenCodeUsage `json:"opencode"`
}

// Billing reports where the request was billed. known is false when the
// gateway did not send pricing information at all.
func (u Usage) Billing() (source string, cost float64, known bool) {
	if u.OpenCode != nil && u.OpenCode.BillingSource != "" {
		return u.OpenCode.BillingSource, u.OpenCode.ListCost, true
	}
	if u.Cost != nil {
		return "", *u.Cost, true
	}
	return "", 0, false
}

// Result is the final assistant message and usage of one completion.
type Result struct {
	Message   Message
	Reasoning string
	Usage     Usage
}
