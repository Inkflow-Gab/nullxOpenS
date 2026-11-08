package tools

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"unicode/utf8"
)

const maxMatches = 1000

func registerGlob(r *Registry) {
	r.Add(Tool{
		Name:        "glob",
		Description: "Find files by glob pattern, for example **/*.go.",
		Parameters: object(map[string]any{
			"pattern": stringProperty("Glob pattern."),
			"path":    stringProperty("Root directory (default '.')."),
		}, "pattern"),
		Run: runGlob,
	})
}

type globArgs struct {
	Pattern string `json:"pattern"`
	Path    string `json:"path"`
}

func runGlob(_ context.Context, raw json.RawMessage) (string, error) {
	var args globArgs
	if err := json.Unmarshal(raw, &args); err != nil {
		return "", err
	}
	if strings.TrimSpace(args.Pattern) == "" {
		return "", fmt.Errorf("pattern is required")
	}
	root := args.Path
	if strings.TrimSpace(root) == "" {
		root = "."
	}
	matcher, err := compileGlob(args.Pattern)
	if err != nil {
		return "", err
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
		rel, err := filepath.Rel(root, path)
		if err != nil {
			rel = path
		}
		matches := matcher.MatchString(filepath.ToSlash(rel))
		if !matches && !strings.Contains(args.Pattern, "/") {
			matches = matcher.MatchString(entry.Name())
		}
		if matches {
			results = append(results, path)
		}
		if len(results) >= maxMatches {
			return filepath.SkipAll
		}
		return nil
	})
	if len(results) == 0 {
		return "(no matches)", nil
	}
	return strings.Join(results, "\n"), nil
}

func skipDir(name string) bool {
	switch name {
	case ".git", "node_modules", "vendor", ".idea", ".venv", "__pycache__", "dist", "build":
		return true
	}
	return false
}

// compileGlob converts a slash-separated glob into a regular expression.
// "**/" matches zero or more directory segments, "**" matches anything,
// "*" matches within a segment, and "?" matches one non-slash character.
func compileGlob(pattern string) (*regexp.Regexp, error) {
	pattern = filepath.ToSlash(pattern)
	var builder strings.Builder
	builder.WriteString("^")
	for index := 0; index < len(pattern); {
		switch pattern[index] {
		case '*':
			if index+1 < len(pattern) && pattern[index+1] == '*' {
				if index+2 < len(pattern) && pattern[index+2] == '/' {
					builder.WriteString("(?:.*/)?")
					index += 3
					continue
				}
				builder.WriteString(".*")
				index += 2
				continue
			}
			builder.WriteString("[^/]*")
			index++
		case '?':
			builder.WriteString("[^/]")
			index++
		default:
			_, size := utf8.DecodeRuneInString(pattern[index:])
			builder.WriteString(regexp.QuoteMeta(pattern[index : index+size]))
			index += size
		}
	}
	builder.WriteString("$")
	return regexp.Compile(builder.String())
}
