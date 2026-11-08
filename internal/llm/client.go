package llm

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"sort"
	"strings"
	"time"
)

// Client talks to an OpenAI-compatible gateway.
type Client struct {
	BaseURL string
	APIKey  string
	HTTP    *http.Client
}

// New returns a client for baseURL. timeout bounds each HTTP request.
func New(baseURL, apiKey string, timeout time.Duration) *Client {
	return &Client{
		BaseURL: strings.TrimRight(baseURL, "/"),
		APIKey:  apiKey,
		HTTP:    &http.Client{Timeout: timeout},
	}
}

type apiError struct {
	Message string `json:"message"`
	Type    string `json:"type"`
	Code    any    `json:"code"`
}

func (c *Client) endpoint(path string) string {
	return c.BaseURL + path
}

func (c *Client) authorize(req *http.Request) {
	if c.APIKey != "" {
		req.Header.Set("Authorization", "Bearer "+c.APIKey)
	}
}

// Stream sends a chat request and invokes onDelta for each content fragment.
// It returns the completed assistant message, including any tool calls.
func (c *Client) Stream(ctx context.Context, request ChatRequest, onDelta func(string)) (Result, error) {
	request.Stream = true
	body, err := json.Marshal(request)
	if err != nil {
		return Result{}, err
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.endpoint("/chat/completions"), bytes.NewReader(body))
	if err != nil {
		return Result{}, err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Accept", "text/event-stream")
	c.authorize(req)
	resp, err := c.HTTP.Do(req)
	if err != nil {
		return Result{}, err
	}
	defer resp.Body.Close()
	if resp.StatusCode/100 != 2 {
		snippet, _ := io.ReadAll(io.LimitReader(resp.Body, 8<<10))
		return Result{}, fmt.Errorf("upstream %s: %s", resp.Status, strings.TrimSpace(string(snippet)))
	}
	if !strings.Contains(resp.Header.Get("Content-Type"), "text/event-stream") {
		return decodeResponse(resp.Body)
	}
	return parseStream(resp.Body, onDelta)
}

func decodeResponse(body io.Reader) (Result, error) {
	var response struct {
		Choices []struct {
			Message Message `json:"message"`
		} `json:"choices"`
		Usage Usage     `json:"usage"`
		Error *apiError `json:"error"`
	}
	if err := json.NewDecoder(body).Decode(&response); err != nil {
		return Result{}, err
	}
	if response.Error != nil {
		return Result{}, fmt.Errorf("upstream: %s", response.Error.Message)
	}
	if len(response.Choices) == 0 {
		return Result{}, fmt.Errorf("upstream returned no choices")
	}
	return Result{Message: response.Choices[0].Message, Usage: response.Usage}, nil
}

type streamChunk struct {
	Choices []struct {
		Delta struct {
			Content   string `json:"content"`
			ToolCalls []struct {
				Index    int    `json:"index"`
				ID       string `json:"id"`
				Type     string `json:"type"`
				Function struct {
					Name      string `json:"name"`
					Arguments string `json:"arguments"`
				} `json:"function"`
			} `json:"tool_calls"`
		} `json:"delta"`
		FinishReason *string `json:"finish_reason"`
	} `json:"choices"`
	Usage *Usage    `json:"usage"`
	Error *apiError `json:"error"`
}

type toolAccumulator struct {
	id, kind, name string
	args           strings.Builder
}

func parseStream(body io.Reader, onDelta func(string)) (Result, error) {
	scanner := bufio.NewScanner(body)
	scanner.Buffer(make([]byte, 0, 64<<10), 16<<20)
	var content strings.Builder
	var usage Usage
	calls := map[int]*toolAccumulator{}
	for scanner.Scan() {
		line := scanner.Text()
		if line == "" || strings.HasPrefix(line, ":") {
			continue
		}
		if !strings.HasPrefix(line, "data:") {
			continue
		}
		payload := strings.TrimSpace(strings.TrimPrefix(line, "data:"))
		if payload == "[DONE]" {
			break
		}
		var chunk streamChunk
		if err := json.Unmarshal([]byte(payload), &chunk); err != nil {
			continue
		}
		if chunk.Error != nil {
			return Result{}, fmt.Errorf("upstream: %s", chunk.Error.Message)
		}
		if chunk.Usage != nil {
			usage = *chunk.Usage
		}
		for _, choice := range chunk.Choices {
			if choice.Delta.Content != "" {
				content.WriteString(choice.Delta.Content)
				if onDelta != nil {
					onDelta(choice.Delta.Content)
				}
			}
			for _, call := range choice.Delta.ToolCalls {
				slot := calls[call.Index]
				if slot == nil {
					slot = &toolAccumulator{}
					calls[call.Index] = slot
				}
				if call.ID != "" {
					slot.id = call.ID
				}
				if call.Type != "" {
					slot.kind = call.Type
				}
				if call.Function.Name != "" {
					slot.name += call.Function.Name
				}
				if call.Function.Arguments != "" {
					slot.args.WriteString(call.Function.Arguments)
				}
			}
		}
	}
	if err := scanner.Err(); err != nil {
		return Result{}, err
	}
	indexes := make([]int, 0, len(calls))
	for index := range calls {
		indexes = append(indexes, index)
	}
	sort.Ints(indexes)
	message := Message{Role: "assistant", Content: content.String()}
	for _, index := range indexes {
		slot := calls[index]
		kind := slot.kind
		if kind == "" {
			kind = "function"
		}
		message.ToolCalls = append(message.ToolCalls, ToolCall{
			ID:   slot.id,
			Type: kind,
			Function: FunctionCall{
				Name:      slot.name,
				Arguments: slot.args.String(),
			},
		})
	}
	return Result{Message: message, Usage: usage}, nil
}

// ModelCost is the per-million-token price reported by the gateway.
type ModelCost struct {
	Input  *float64 `json:"input"`
	Output *float64 `json:"output"`
}

// ModelInfo is one entry of the gateway model list.
type ModelInfo struct {
	ID            string     `json:"id"`
	OwnedBy       string     `json:"owned_by"`
	ContextWindow int        `json:"context_window"`
	ToolCall      bool       `json:"tool_call"`
	Cost          *ModelCost `json:"cost"`
	Metadata      struct {
		Cost *ModelCost `json:"cost"`
	} `json:"metadata"`
}

// preferredFreeModels is the free-tier order recommended by the OpenCode
// UNLIMITED installer, best first. A model the gateway adds later is still
// selected when none of these are advertised.
var preferredFreeModels = []string{
	"deepseek-v4.1-flash-free",
	"crouton-alpha-free",
	"nemotron-3.5-super-vl-free",
	"beam-free",
	"pulse-alpha-free",
	"big-pickle",
	"nemotron-3.5-lightning-free",
	"glm-5.3-flash-free",
	"flint-40b-free",
	"mimo-v2.6-flash-free",
}

// IsFree reports whether the gateway advertises the model as free-tier: its ID
// contains "free", or its price is zero for both input and output.
func (m ModelInfo) IsFree() bool {
	if strings.Contains(strings.ToLower(m.ID), "free") {
		return true
	}
	cost := m.Cost
	if cost == nil {
		cost = m.Metadata.Cost
	}
	if cost != nil && cost.Input != nil && cost.Output != nil {
		return *cost.Input == 0 && *cost.Output == 0
	}
	return false
}

// ResolveModel picks the model to use. A concrete preferred ID that exists in
// the catalog wins; otherwise the recommended free model order is tried, then
// any free model that supports tool calls, then any free model, and finally the
// first listed model. It reports false when the catalog is empty.
func ResolveModel(models []ModelInfo, preferred string) (ModelInfo, bool) {
	preferred = strings.TrimSpace(preferred)
	if preferred != "" && preferred != "auto" {
		for _, model := range models {
			if model.ID == preferred {
				return model, true
			}
		}
	}
	for _, id := range preferredFreeModels {
		for _, model := range models {
			if model.ID == id && model.IsFree() {
				return model, true
			}
		}
	}
	for _, model := range models {
		if model.IsFree() && model.ToolCall {
			return model, true
		}
	}
	for _, model := range models {
		if model.IsFree() {
			return model, true
		}
	}
	if len(models) > 0 {
		return models[0], true
	}
	return ModelInfo{}, false
}

// Models fetches the available model IDs from the gateway.
func (c *Client) Models(ctx context.Context) ([]ModelInfo, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, c.endpoint("/models"), nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("Accept", "application/json")
	c.authorize(req)
	resp, err := c.HTTP.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode/100 != 2 {
		snippet, _ := io.ReadAll(io.LimitReader(resp.Body, 4<<10))
		return nil, fmt.Errorf("upstream %s: %s", resp.Status, strings.TrimSpace(string(snippet)))
	}
	data, err := io.ReadAll(io.LimitReader(resp.Body, 4<<20))
	if err != nil {
		return nil, err
	}
	var envelope struct {
		Data []ModelInfo `json:"data"`
	}
	if err := json.Unmarshal(data, &envelope); err == nil && envelope.Data != nil {
		return envelope.Data, nil
	}
	var list []ModelInfo
	if err := json.Unmarshal(data, &list); err == nil {
		return list, nil
	}
	return nil, fmt.Errorf("unrecognized model list response")
}

// Health fetches the gateway readiness document from /healthz. The API base URL
// is expected to end in /v1; the suffix is stripped because health answers at
// the server root.
func (c *Client) Health(ctx context.Context) (map[string]any, error) {
	base := strings.TrimRight(c.BaseURL, "/")
	base = strings.TrimSuffix(base, "/v1")
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, base+"/healthz", nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("Accept", "application/json")
	resp, err := c.HTTP.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	var document map[string]any
	if err := json.NewDecoder(io.LimitReader(resp.Body, 1<<20)).Decode(&document); err != nil {
		return nil, err
	}
	if resp.StatusCode/100 != 2 {
		return document, fmt.Errorf("health answered %s", resp.Status)
	}
	return document, nil
}
