package agent

import (
	"fmt"
	"os"
	"path/filepath"
	"runtime"
	"strings"

	"github.com/Inkflow-Gab/nullxOpenS/internal/config"
)

const maxContextBytes = 32 << 10

func systemPrompt(cfg config.Config, cwd string) string {
	var builder strings.Builder
	builder.WriteString("You are nullx, a terminal coding agent. ")
	builder.WriteString("You help with software engineering tasks by reading, writing, and running code.\n\n")
	fmt.Fprintf(&builder, "Working directory: %s\n", cwd)
	fmt.Fprintf(&builder, "Operating system: %s\n\n", runtime.GOOS)
	builder.WriteString("Rules:\n")
	builder.WriteString("- Inspect the code before changing it; read the surrounding context.\n")
	builder.WriteString("- Use tools for real work instead of guessing at file contents.\n")
	builder.WriteString("- Keep changes focused and leave the tree in a working state.\n")
	builder.WriteString("- Prefer small, verifiable steps and report what you actually did.\n")
	builder.WriteString("- Never invent command output; run the command when you need it.\n\n")
	if strings.TrimSpace(cfg.SystemPrompt) != "" {
		builder.WriteString(cfg.SystemPrompt)
		builder.WriteString("\n\n")
	}
	if context := readContextFiles(cfg, cwd); context != "" {
		builder.WriteString("Project instructions:\n")
		builder.WriteString(context)
		builder.WriteString("\n")
	}
	return builder.String()
}

func readContextFiles(cfg config.Config, cwd string) string {
	var builder strings.Builder
	seen := map[string]bool{}
	for _, name := range cfg.ContextFiles {
		path := name
		if !filepath.IsAbs(path) {
			path = filepath.Join(cwd, name)
		}
		if seen[path] {
			continue
		}
		seen[path] = true
		data, err := os.ReadFile(path)
		if err != nil {
			continue
		}
		if len(data) > maxContextBytes {
			data = data[:maxContextBytes]
		}
		fmt.Fprintf(&builder, "### %s\n%s\n\n", name, strings.TrimSpace(string(data)))
	}
	return builder.String()
}
