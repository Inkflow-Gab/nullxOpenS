// Package tools implements the built-in tools of the nullx agent.
package tools

import (
	"context"
	"encoding/json"
	"fmt"
	"sort"

	"github.com/Inkflow-Gab/nullxOpenS/internal/llm"
)

// Func is the implementation of one tool.
type Func func(ctx context.Context, args json.RawMessage) (string, error)

// Tool is one callable tool with its schema and implementation.
type Tool struct {
	Name        string
	Description string
	Parameters  map[string]any
	Run         Func
}

// Registry holds the tools available to the agent.
type Registry struct {
	tools map[string]*Tool
	order []string
}

// NewRegistry returns an empty registry.
func NewRegistry() *Registry {
	return &Registry{tools: map[string]*Tool{}}
}

// Add registers a tool, replacing an existing tool of the same name.
func (r *Registry) Add(tool Tool) {
	if _, exists := r.tools[tool.Name]; !exists {
		r.order = append(r.order, tool.Name)
	}
	r.tools[tool.Name] = &tool
}

// Get looks up a tool by name.
func (r *Registry) Get(name string) (*Tool, bool) {
	tool, ok := r.tools[name]
	return tool, ok
}

// Names returns the registered tool names in sorted order.
func (r *Registry) Names() []string {
	names := append([]string(nil), r.order...)
	sort.Strings(names)
	return names
}

// Schemas returns the tool definitions advertised to the model.
func (r *Registry) Schemas() []llm.Tool {
	schemas := make([]llm.Tool, 0, len(r.order))
	for _, name := range r.order {
		tool := r.tools[name]
		schemas = append(schemas, llm.Tool{
			Type: "function",
			Function: llm.ToolDefinition{
				Name:        tool.Name,
				Description: tool.Description,
				Parameters:  tool.Parameters,
			},
		})
	}
	return schemas
}

// Describe returns one human-readable line per tool.
func (r *Registry) Describe() []string {
	lines := make([]string, 0, len(r.order))
	for _, name := range r.order {
		lines = append(lines, fmt.Sprintf("%-8s %s", name, r.tools[name].Description))
	}
	return lines
}

// Builtins returns the default tool set.
func Builtins() *Registry {
	registry := NewRegistry()
	registerFS(registry)
	registerBash(registry)
	registerGlob(registry)
	registerGrep(registry)
	return registry
}
