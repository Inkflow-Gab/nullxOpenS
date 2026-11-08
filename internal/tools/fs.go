package tools

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

const maxReadBytes = 1 << 20

func registerFS(r *Registry) {
	r.Add(Tool{
		Name:        "read",
		Description: "Read a text file with line numbers.",
		Parameters: object(map[string]any{
			"path":   stringProperty("File path, relative to the working directory."),
			"offset": integerProperty("First line to return (1-based)."),
			"limit":  integerProperty("Maximum number of lines to return (default 2000)."),
		}, "path"),
		Run: runRead,
	})
	r.Add(Tool{
		Name:        "write",
		Description: "Create or overwrite a file with the given content.",
		Parameters: object(map[string]any{
			"path":    stringProperty("File path."),
			"content": stringProperty("Full file content."),
		}, "path", "content"),
		Run: runWrite,
	})
	r.Add(Tool{
		Name:        "edit",
		Description: "Replace an exact occurrence of old text in a file. Fails when the old text is ambiguous unless replaceAll is set.",
		Parameters: object(map[string]any{
			"path":       stringProperty("File path."),
			"old":        stringProperty("Exact text to replace."),
			"new":        stringProperty("Replacement text."),
			"replaceAll": map[string]any{"type": "boolean", "description": "Replace every occurrence."},
		}, "path", "old", "new"),
		Run: runEdit,
	})
	r.Add(Tool{
		Name:        "ls",
		Description: "List the entries of a directory.",
		Parameters: object(map[string]any{
			"path": stringProperty("Directory path (default '.')."),
		}),
		Run: runList,
	})
}

type readArgs struct {
	Path   string `json:"path"`
	Offset int    `json:"offset"`
	Limit  int    `json:"limit"`
}

func runRead(_ context.Context, raw json.RawMessage) (string, error) {
	var args readArgs
	if err := json.Unmarshal(raw, &args); err != nil {
		return "", err
	}
	if strings.TrimSpace(args.Path) == "" {
		return "", fmt.Errorf("path is required")
	}
	info, err := os.Stat(args.Path)
	if err != nil {
		return "", err
	}
	if info.IsDir() {
		return "", fmt.Errorf("%s is a directory", args.Path)
	}
	data, err := os.ReadFile(args.Path)
	if err != nil {
		return "", err
	}
	truncated := false
	if len(data) > maxReadBytes {
		data = data[:maxReadBytes]
		truncated = true
	}
	lines := strings.Split(strings.ReplaceAll(string(data), "\r\n", "\n"), "\n")
	offset := args.Offset
	if offset < 1 {
		offset = 1
	}
	limit := args.Limit
	if limit < 1 {
		limit = 2000
	}
	if offset-1 >= len(lines) {
		return "", fmt.Errorf("offset %d is beyond end of file (%d lines)", offset, len(lines))
	}
	end := offset - 1 + limit
	if end > len(lines) {
		end = len(lines)
	}
	var builder strings.Builder
	for index := offset - 1; index < end; index++ {
		fmt.Fprintf(&builder, "%6d\t%s\n", index+1, lines[index])
	}
	if truncated {
		builder.WriteString("\n[truncated at 1 MiB]\n")
	}
	return builder.String(), nil
}

type writeArgs struct {
	Path    string `json:"path"`
	Content string `json:"content"`
}

func runWrite(_ context.Context, raw json.RawMessage) (string, error) {
	var args writeArgs
	if err := json.Unmarshal(raw, &args); err != nil {
		return "", err
	}
	if strings.TrimSpace(args.Path) == "" {
		return "", fmt.Errorf("path is required")
	}
	if dir := filepath.Dir(args.Path); dir != "" && dir != "." {
		if err := os.MkdirAll(dir, 0o755); err != nil {
			return "", err
		}
	}
	if err := os.WriteFile(args.Path, []byte(args.Content), 0o644); err != nil {
		return "", err
	}
	return fmt.Sprintf("wrote %d bytes to %s", len(args.Content), args.Path), nil
}

type editArgs struct {
	Path       string `json:"path"`
	FilePath   string `json:"filePath"`
	Old        string `json:"old"`
	OldString  string `json:"oldString"`
	New        string `json:"new"`
	NewString  string `json:"newString"`
	ReplaceAll bool   `json:"replaceAll"`
}

func runEdit(_ context.Context, raw json.RawMessage) (string, error) {
	var args editArgs
	if err := json.Unmarshal(raw, &args); err != nil {
		return "", err
	}
	path := firstNonEmpty(args.Path, args.FilePath)
	old := firstNonEmpty(args.Old, args.OldString)
	replacement := firstNonEmpty(args.New, args.NewString)
	if path == "" {
		return "", fmt.Errorf("path is required")
	}
	if old == "" {
		return "", fmt.Errorf("old text must not be empty")
	}
	data, err := os.ReadFile(path)
	if err != nil {
		return "", err
	}
	text := string(data)
	count := strings.Count(text, old)
	if count == 0 {
		return "", fmt.Errorf("old text was not found in %s", path)
	}
	if count > 1 && !args.ReplaceAll {
		return "", fmt.Errorf("old text matches %d places in %s; provide more context or set replaceAll", count, path)
	}
	updated := strings.Replace(text, old, replacement, 1)
	if args.ReplaceAll {
		updated = strings.ReplaceAll(text, old, replacement)
	}
	if err := os.WriteFile(path, []byte(updated), 0o644); err != nil {
		return "", err
	}
	return fmt.Sprintf("edited %s", path), nil
}

func firstNonEmpty(values ...string) string {
	for _, value := range values {
		if value != "" {
			return value
		}
	}
	return ""
}

type listArgs struct {
	Path string `json:"path"`
}

func runList(_ context.Context, raw json.RawMessage) (string, error) {
	var args listArgs
	if err := json.Unmarshal(raw, &args); err != nil {
		return "", err
	}
	path := args.Path
	if strings.TrimSpace(path) == "" {
		path = "."
	}
	entries, err := os.ReadDir(path)
	if err != nil {
		return "", err
	}
	var builder strings.Builder
	for _, entry := range entries {
		name := entry.Name()
		if entry.IsDir() {
			name += "/"
		}
		builder.WriteString(name)
		builder.WriteByte('\n')
	}
	if builder.Len() == 0 {
		return "(empty directory)", nil
	}
	return builder.String(), nil
}
