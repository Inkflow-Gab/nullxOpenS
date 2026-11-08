package tools

import (
	"bufio"
	"context"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"strings"
)

const (
	maxGrepFileBytes = 2 << 20
	maxGrepMatches   = 500
)

func registerGrep(r *Registry) {
	r.Add(Tool{
		Name:        "grep",
		Description: "Search file contents with a regular expression.",
		Parameters: object(map[string]any{
			"pattern": stringProperty("Go regular expression."),
			"path":    stringProperty("Root directory (default '.')."),
			"include": stringProperty("Optional glob filter such as *.go."),
		}, "pattern"),
		Run: runGrep,
	})
}

type grepArgs struct {
	Pattern string `json:"pattern"`
	Path    string `json:"path"`
	Include string `json:"include"`
}

func runGrep(_ context.Context, raw json.RawMessage) (string, error) {
	var args grepArgs
	if err := json.Unmarshal(raw, &args); err != nil {
		return "", err
	}
	expression, err := regexp.Compile(args.Pattern)
	if err != nil {
		return "", fmt.Errorf("invalid pattern: %w", err)
	}
	root := args.Path
	if strings.TrimSpace(root) == "" {
		root = "."
	}
	var include *regexp.Regexp
	if strings.TrimSpace(args.Include) != "" {
		include, err = compileGlob(args.Include)
		if err != nil {
			return "", err
		}
	}
	results := make([]string, 0, 64)
	filepath.WalkDir(root, func(path string, entry os.DirEntry, walkErr error) error {
		if walkErr != nil {
			return nil
		}
		if entry.IsDir() {
			if skipDir(entry.Name()) {
				return filepath.SkipDir
			}
			return nil
		}
		if include != nil && !include.MatchString(entry.Name()) {
			return nil
		}
		info, err := entry.Info()
		if err != nil || info.Size() > maxGrepFileBytes {
			return nil
		}
		file, err := os.Open(path)
		if err != nil {
			return nil
		}
		defer file.Close()
		scanner := bufio.NewScanner(file)
		scanner.Buffer(make([]byte, 0, 64<<10), 1<<20)
		lineNumber := 0
		for scanner.Scan() {
			lineNumber++
			line := scanner.Text()
			if expression.MatchString(line) {
				results = append(results, fmt.Sprintf("%s:%d:%s", path, lineNumber, line))
				if len(results) >= maxGrepMatches {
					return filepath.SkipAll
				}
			}
		}
		return nil
	})
	if len(results) == 0 {
		return "(no matches)", nil
	}
	return strings.Join(results, "\n"), nil
}
