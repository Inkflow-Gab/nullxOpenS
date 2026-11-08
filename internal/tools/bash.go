package tools

import (
	"context"
	"encoding/json"
	"fmt"
	"os/exec"
	"runtime"
	"strings"
	"time"
)

const maxCommandOutput = 64 << 10

func registerBash(r *Registry) {
	r.Add(Tool{
		Name:        "bash",
		Description: "Run a shell command in the working directory and return its combined output.",
		Parameters: object(map[string]any{
			"command":         stringProperty("Command to run."),
			"timeout_seconds": integerProperty("Timeout in seconds (default 120)."),
		}, "command"),
		Run: runBash,
	})
}

type bashArgs struct {
	Command        string `json:"command"`
	Cmd            string `json:"cmd"`
	Script         string `json:"script"`
	TimeoutSeconds int    `json:"timeout_seconds"`
	TimeoutMS      int    `json:"timeout"`
	Workdir        string `json:"workdir"`
}

func runBash(ctx context.Context, raw json.RawMessage) (string, error) {
	var args bashArgs
	if err := json.Unmarshal(raw, &args); err != nil {
		return "", err
	}
	command := firstNonEmpty(args.Command, args.Cmd, args.Script)
	if strings.TrimSpace(command) == "" {
		return "", fmt.Errorf("command is required")
	}
	timeout := 120 * time.Second
	if args.TimeoutSeconds > 0 {
		timeout = time.Duration(args.TimeoutSeconds) * time.Second
	} else if args.TimeoutMS > 0 {
		timeout = time.Duration(args.TimeoutMS) * time.Millisecond
	}
	commandCtx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	shell, flag := "sh", "-c"
	if runtime.GOOS == "windows" {
		shell, flag = "cmd", "/C"
	}
	cmd := exec.CommandContext(commandCtx, shell, flag, command)
	if strings.TrimSpace(args.Workdir) != "" {
		cmd.Dir = args.Workdir
	}
	output, err := cmd.CombinedOutput()
	text := string(output)
	if len(text) > maxCommandOutput {
		text = text[:maxCommandOutput] + "\n[output truncated]\n"
	}
	if commandCtx.Err() == context.DeadlineExceeded {
		return text + "\n[command timed out]", nil
	}
	if err != nil {
		if exit, ok := err.(*exec.ExitError); ok {
			return fmt.Sprintf("%s\n[exit status %d]", text, exit.ExitCode()), nil
		}
		return text, err
	}
	if strings.TrimSpace(text) == "" {
		return "(no output)", nil
	}
	return text, nil
}
