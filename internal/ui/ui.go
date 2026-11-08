// Package ui handles terminal input and output for nullx.
package ui

import (
	"bufio"
	"fmt"
	"io"
	"os"
	"strings"
)

// Sink is the output surface the agent writes to. The plain terminal UI and
// the Bubble Tea TUI both implement it.
type Sink interface {
	Interactive() bool
	Printf(format string, args ...any)
	Stream(text string)
	Reasoning(text string)
	Newline()
	ToolStart(name, arguments string)
	ToolResult(name, output string)
	Billing(source string, free bool, cost float64, known bool)
	Ask(question string) bool
}

// UI wraps the terminal streams.
type UI struct {
	in          *bufio.Reader
	out         io.Writer
	interactive bool
	color       bool
}

// New returns a UI over in and out. Prompting and color are enabled only when
// in is a terminal.
func New(in io.Reader, out io.Writer) *UI {
	interactive := false
	if file, ok := in.(*os.File); ok {
		if info, err := file.Stat(); err == nil && info.Mode()&os.ModeCharDevice != 0 {
			interactive = true
		}
	}
	return &UI{in: bufio.NewReader(in), out: out, interactive: interactive, color: interactive}
}

// Interactive reports whether the input is a terminal.
func (u *UI) Interactive() bool { return u.interactive }

// Printf writes one formatted line.
func (u *UI) Printf(format string, args ...any) {
	fmt.Fprintf(u.out, format, args...)
	fmt.Fprintln(u.out)
}

// Stream writes a fragment without a newline.
func (u *UI) Stream(text string) {
	fmt.Fprint(u.out, text)
}

// Reasoning is ignored by the plain terminal UI; piped output stays clean.
func (u *UI) Reasoning(string) {}

// Billing is ignored by the plain terminal UI.
func (u *UI) Billing(string, bool, float64, bool) {}

// Newline ends the current output line.
func (u *UI) Newline() {
	fmt.Fprintln(u.out)
}

// ToolStart announces a tool invocation.
func (u *UI) ToolStart(name, arguments string) {
	label := u.paint("\x1b[34m", name)
	fmt.Fprintf(u.out, "\n%s %s\n", label, oneLine(arguments, 240))
}

// ToolResult prints a bounded tool result.
func (u *UI) ToolResult(name, output string) {
	label := u.paint("\x1b[2m", "result")
	body := output
	if strings.TrimSpace(body) == "" {
		body = "(empty)"
	}
	if len(body) > 1200 {
		body = body[:1200] + "\n[truncated]"
	}
	fmt.Fprintf(u.out, "%s %s\n", label, body)
}

// Ask shows a yes/no question and reports the answer.
func (u *UI) Ask(question string) bool {
	if !u.interactive {
		return false
	}
	fmt.Fprintf(u.out, "%s [y/N] ", question)
	line, err := u.in.ReadString('\n')
	if err != nil {
		return false
	}
	line = strings.ToLower(strings.TrimSpace(line))
	return line == "y" || line == "yes"
}

// ReadLine shows prompt and returns one line, or io.EOF.
func (u *UI) ReadLine(prompt string) (string, error) {
	fmt.Fprint(u.out, prompt)
	line, err := u.in.ReadString('\n')
	if err != nil {
		if err == io.EOF && line != "" {
			return strings.TrimRight(line, "\r\n"), nil
		}
		return "", err
	}
	return strings.TrimRight(line, "\r\n"), nil
}

func (u *UI) paint(code, text string) string {
	if !u.color {
		return text
	}
	return code + text + "\x1b[0m"
}

func oneLine(value string, limit int) string {
	value = strings.ReplaceAll(value, "\n", " ")
	if len(value) <= limit {
		return value
	}
	return value[:limit] + "..."
}
