// Package tui implements the full-screen Bubble Tea interface.
package tui

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/charmbracelet/bubbles/spinner"
	"github.com/charmbracelet/bubbles/textarea"
	"github.com/charmbracelet/bubbles/viewport"
	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"

	"github.com/Inkflow-Gab/nullxOpenS/internal/agent"
	"github.com/Inkflow-Gab/nullxOpenS/internal/config"
	"github.com/Inkflow-Gab/nullxOpenS/internal/llm"
	"github.com/Inkflow-Gab/nullxOpenS/internal/session"
	"github.com/Inkflow-Gab/nullxOpenS/internal/tools"
)

var (
	accentStyle = lipgloss.NewStyle().Foreground(lipgloss.Color("212")).Bold(true)
	userStyle   = lipgloss.NewStyle().Foreground(lipgloss.Color("39")).Bold(true)
	dimStyle    = lipgloss.NewStyle().Foreground(lipgloss.Color("241"))
	toolStyle   = lipgloss.NewStyle().Foreground(lipgloss.Color("214")).Bold(true)
	resultStyle = lipgloss.NewStyle().Foreground(lipgloss.Color("245"))
	inputStyle  = lipgloss.NewStyle().
			Border(lipgloss.RoundedBorder()).
			BorderForeground(lipgloss.Color("62")).
			Padding(0, 1)
	askStyle = inputStyle.BorderForeground(lipgloss.Color("214"))
)

type entryKind int

const (
	entryUser entryKind = iota
	entryAssistant
	entryTool
	entryResult
	entrySystem
)

type entry struct {
	kind entryKind
	name string
	text string
}

type eventKind int

const (
	evStream eventKind = iota
	evNewline
	evPrint
	evToolStart
	evToolResult
	evAsk
)

type event struct {
	kind     eventKind
	name     string
	text     string
	question string
	reply    chan bool
}

type runDoneMsg struct {
	err error
}

// Model is the Bubble Tea application.
type Model struct {
	cfg        config.Config
	runner     *agent.Agent
	sess       *session.Session
	version    string
	configPath string
	prog       *tea.Program

	width  int
	height int
	input  textarea.Model
	view   viewport.Model
	spin   spinner.Model

	entries []entry
	stream  strings.Builder
	pending strings.Builder
	last    time.Time

	busy        bool
	cancel      context.CancelFunc
	mode        string
	askQuestion string
	askReply    chan bool
}

// New builds the TUI and the agent it drives.
func New(cfg config.Config, sess *session.Session, version, configPath string) *Model {
	input := textarea.New()
	input.Placeholder = "Ask nullx to build something…"
	input.Prompt = accentStyle.Render("❯ ")
	input.ShowLineNumbers = false
	input.CharLimit = 0
	input.MaxHeight = 6
	input.SetWidth(80)
	input.SetHeight(1)
	input.KeyMap.InsertNewline.SetKeys("alt+enter")
	input.Focus()

	spin := spinner.New()
	spin.Spinner = spinner.Dot
	spin.Style = accentStyle

	view := viewport.New(80, 20)
	view.MouseWheelEnabled = true

	model := &Model{
		cfg: cfg, sess: sess, version: version, configPath: configPath,
		input: input, view: view, spin: spin,
	}
	model.runner = agent.New(
		cfg,
		llm.New(cfg.BaseURL, cfg.APIKey, time.Duration(cfg.Timeout)*time.Second),
		tools.Builtins(),
		model,
		sess,
	)
	model.addSystem(fmt.Sprintf("nullx %s · %s", version, cfg.Model))
	model.addSystem(fmt.Sprintf("gateway %s · session %s", cfg.BaseURL, sess.ID))
	model.addSystem("type /help for commands")
	model.relayout()
	return model
}

// Run starts the program and blocks until it exits.
func Run(cfg config.Config, sess *session.Session, version, configPath string) error {
	model := New(cfg, sess, version, configPath)
	program := tea.NewProgram(model, tea.WithAltScreen(), tea.WithMouseCellMotion())
	model.prog = program
	_, err := program.Run()
	return err
}

// Init implements tea.Model.
func (m *Model) Init() tea.Cmd {
	return tea.Batch(textarea.Blink, m.spin.Tick)
}

// Interactive implements ui.Sink.
func (m *Model) Interactive() bool { return true }

func (m *Model) emit(ev event) {
	if m.prog != nil {
		m.prog.Send(ev)
	}
}

// flushStream sends the coalesced streaming text.
func (m *Model) flushStream() {
	if m.pending.Len() == 0 {
		return
	}
	text := m.pending.String()
	m.pending.Reset()
	m.last = time.Now()
	m.emit(event{kind: evStream, text: text})
}

// Stream implements ui.Sink.
func (m *Model) Stream(text string) {
	if text == "" {
		return
	}
	m.pending.WriteString(text)
	// Coalesce deltas so a long answer does not redraw on every token.
	if m.pending.Len() < 512 && time.Since(m.last) < 40*time.Millisecond {
		return
	}
	m.flushStream()
}

// Newline implements ui.Sink.
func (m *Model) Newline() {
	m.flushStream()
	m.emit(event{kind: evNewline})
}

// Printf implements ui.Sink.
func (m *Model) Printf(format string, args ...any) {
	m.flushStream()
	m.emit(event{kind: evPrint, text: fmt.Sprintf(format, args...)})
}

// ToolStart implements ui.Sink.
func (m *Model) ToolStart(name, arguments string) {
	m.flushStream()
	m.emit(event{kind: evToolStart, name: name, text: arguments})
}

// ToolResult implements ui.Sink.
func (m *Model) ToolResult(name, output string) {
	m.flushStream()
	m.emit(event{kind: evToolResult, name: name, text: output})
}

// Ask implements ui.Sink.
func (m *Model) Ask(question string) bool {
	reply := make(chan bool, 1)
	m.emit(event{kind: evAsk, question: question, reply: reply})
	return <-reply
}

// Update implements tea.Model.
func (m *Model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	switch msg := msg.(type) {
	case tea.WindowSizeMsg:
		m.width, m.height = msg.Width, msg.Height
		m.relayout()
		return m, nil
	case event:
		m.handleEvent(msg)
		return m, nil
	case runDoneMsg:
		m.busy = false
		m.cancel = nil
		if m.stream.Len() > 0 {
			m.addEntry(entry{kind: entryAssistant, text: m.stream.String()})
			m.stream.Reset()
		}
		if msg.err != nil {
			if errors.Is(msg.err, context.Canceled) {
				m.addSystem("interrupted")
			} else {
				m.addSystem("error: " + msg.err.Error())
			}
		}
		m.relayout()
		return m, nil
	case tea.MouseMsg:
		var cmd tea.Cmd
		m.view, cmd = m.view.Update(msg)
		return m, cmd
	case tea.KeyMsg:
		return m.handleKey(msg)
	case spinner.TickMsg:
		if !m.busy {
			return m, nil
		}
		var cmd tea.Cmd
		m.spin, cmd = m.spin.Update(msg)
		return m, cmd
	}
	var cmd tea.Cmd
	m.input, cmd = m.input.Update(msg)
	m.resizeInput()
	return m, cmd
}

func (m *Model) handleEvent(ev event) {
	switch ev.kind {
	case evStream:
		m.stream.WriteString(ev.text)
		m.refresh()
	case evNewline:
		if m.stream.Len() > 0 {
			m.addEntry(entry{kind: entryAssistant, text: m.stream.String()})
			m.stream.Reset()
		}
	case evPrint:
		m.addSystem(ev.text)
	case evToolStart:
		m.addEntry(entry{kind: entryTool, name: ev.name, text: ev.text})
	case evToolResult:
		m.addEntry(entry{kind: entryResult, name: ev.name, text: ev.text})
	case evAsk:
		m.mode = "ask"
		m.askQuestion = ev.question
		m.askReply = ev.reply
		m.relayout()
	}
}

func (m *Model) handleKey(msg tea.KeyMsg) (tea.Model, tea.Cmd) {
	if m.mode == "ask" {
		switch msg.String() {
		case "y", "Y", "enter":
			m.replyAsk(true)
		case "n", "N", "esc", "ctrl+c":
			m.replyAsk(false)
		}
		return m, nil
	}

	switch msg.String() {
	case "ctrl+c":
		if m.busy {
			if m.cancel != nil {
				m.cancel()
			}
			return m, nil
		}
		m.stop()
		return m, tea.Quit
	case "ctrl+d":
		if strings.TrimSpace(m.input.Value()) == "" {
			m.stop()
			return m, tea.Quit
		}
	case "enter":
		if m.busy {
			return m, nil
		}
		value := strings.TrimSpace(m.input.Value())
		if value == "" {
			return m, nil
		}
		m.input.Reset()
		m.resizeInput()
		if strings.HasPrefix(value, "/") {
			return m.handleSlash(value)
		}
		m.addEntry(entry{kind: entryUser, text: value})
		m.busy = true
		m.stream.Reset()
		ctx, cancel := context.WithCancel(context.Background())
		m.cancel = cancel
		runner := m.runner
		m.relayout()
		return m, tea.Batch(
			func() tea.Msg { return runDoneMsg{err: runner.Run(ctx, value)} },
			m.spin.Tick,
		)
	case "pgup", "pgdown", "home", "end":
		var cmd tea.Cmd
		m.view, cmd = m.view.Update(msg)
		return m, cmd
	}

	var cmd tea.Cmd
	m.input, cmd = m.input.Update(msg)
	m.resizeInput()
	return m, cmd
}

func (m *Model) handleSlash(line string) (tea.Model, tea.Cmd) {
	fields := strings.Fields(line)
	switch fields[0] {
	case "/exit", "/quit":
		m.stop()
		return m, tea.Quit
	case "/help":
		for _, text := range []string{
			"/clear         reset the conversation",
			"/model <id>    switch model",
			"/tools         list built-in tools",
			"/session       show the session id",
			"/config        show the active config",
			"/exit          quit",
			"",
			"enter send · alt+enter newline · pgup/pgdn scroll · ctrl+c interrupt",
		} {
			m.addSystem(text)
		}
	case "/clear":
		m.runner.Reset()
		m.entries = nil
		m.stream.Reset()
		m.addSystem("conversation cleared")
	case "/model":
		if len(fields) < 2 {
			m.addSystem("current model: " + m.runner.Config.Model)
			break
		}
		m.runner.Config.Model = fields[1]
		m.cfg.Model = fields[1]
		m.addSystem("model set to " + fields[1])
	case "/tools":
		for _, text := range m.runner.Tools.Describe() {
			m.addSystem(text)
		}
	case "/session":
		m.addSystem(fmt.Sprintf("session %s · %d messages", m.sess.ID, len(m.sess.Messages)))
	case "/config":
		data, err := json.MarshalIndent(m.runner.Config.Redacted(), "", "  ")
		if err != nil {
			m.addSystem("error: " + err.Error())
			break
		}
		for _, text := range strings.Split(string(data), "\n") {
			m.addSystem(text)
		}
	default:
		m.addSystem("unknown command " + fields[0])
	}
	m.relayout()
	return m, nil
}

func (m *Model) replyAsk(answer bool) {
	if m.askReply != nil {
		m.askReply <- answer
		m.askReply = nil
	}
	m.mode = "chat"
	m.askQuestion = ""
	m.relayout()
}

func (m *Model) stop() {
	if m.askReply != nil {
		m.askReply <- false
		m.askReply = nil
	}
	if m.cancel != nil {
		m.cancel()
		m.cancel = nil
	}
}

func (m *Model) addEntry(e entry) {
	m.entries = append(m.entries, e)
	m.refresh()
}

func (m *Model) addSystem(text string) {
	m.addEntry(entry{kind: entrySystem, text: text})
}

func (m *Model) refresh() {
	atBottom := m.view.AtBottom()
	m.view.SetContent(m.render())
	if atBottom {
		m.view.GotoBottom()
	}
}

func (m *Model) resizeInput() {
	height := strings.Count(m.input.Value(), "\n") + 1
	if height < 1 {
		height = 1
	}
	if height > 6 {
		height = 6
	}
	if height != m.input.Height() {
		m.input.SetHeight(height)
		m.relayout()
	}
}

func (m *Model) relayout() {
	width := m.termWidth()
	height := m.height
	if height <= 0 {
		height = 24
	}
	m.view.Width = maxInt(20, width-2)
	header := m.headerView(width)
	box := m.inputView(width)
	status := m.statusView(width)
	m.view.Height = height - lipgloss.Height(header) - lipgloss.Height(box) - lipgloss.Height(status) - 3
	if m.view.Height < 3 {
		m.view.Height = 3
	}
	m.view.SetContent(m.render())
	m.view.GotoBottom()
}

func (m *Model) termWidth() int {
	if m.width <= 0 {
		return 80
	}
	return maxInt(20, m.width)
}

// View implements tea.Model.
func (m *Model) View() string {
	width := m.termWidth()
	return m.headerView(width) + "\n" +
		m.view.View() + "\n" +
		m.inputView(width) + "\n" +
		m.statusView(width)
}

func (m *Model) headerView(width int) string {
	left := accentStyle.Render("▌ nullx") + dimStyle.Render(" "+m.version)
	right := dimStyle.Render(m.cfg.Model)
	gap := width - lipgloss.Width(left) - lipgloss.Width(right)
	if gap < 1 {
		gap = 1
	}
	return left + strings.Repeat(" ", gap) + right + "\n" +
		dimStyle.Render(strings.Repeat("─", width))
}

func (m *Model) inputView(width int) string {
	m.input.SetWidth(maxInt(20, width-6))
	if m.mode == "ask" {
		question := "allow " + truncateText(m.askQuestion, maxInt(20, width-24)) + "?"
		return askStyle.Render(toolStyle.Render(question) + dimStyle.Render("  y / n"))
	}
	return inputStyle.Render(m.input.View())
}

func (m *Model) statusView(width int) string {
	if m.mode == "ask" {
		return toolStyle.Render("permission") + dimStyle.Render("  y allow · n deny")
	}
	if m.busy {
		return " " + m.spin.View() + dimStyle.Render(" thinking · ctrl+c interrupt · pgup/pgdn scroll")
	}
	left := dimStyle.Render("enter send · alt+enter newline · /help")
	right := dimStyle.Render("perm:" + m.cfg.Permission)
	gap := width - lipgloss.Width(left) - lipgloss.Width(right)
	if gap < 1 {
		return left
	}
	return left + strings.Repeat(" ", gap) + right
}

func (m *Model) render() string {
	width := maxInt(20, m.view.Width)
	var builder strings.Builder
	for _, e := range m.entries {
		builder.WriteString(m.renderEntry(e, width))
		builder.WriteString("\n")
	}
	if m.stream.Len() > 0 {
		builder.WriteString(m.renderEntry(entry{kind: entryAssistant, text: m.stream.String()}, width))
	}
	return builder.String()
}

func (m *Model) renderEntry(e entry, width int) string {
	switch e.kind {
	case entryUser:
		return userStyle.Render("› ") + wrapText(e.text, width-2)
	case entryAssistant:
		return accentStyle.Render("● ") + wrapText(e.text, width-2)
	case entryTool:
		return "  " + toolStyle.Render(e.name) + dimStyle.Render(" "+oneLine(e.text, maxInt(10, width-6)))
	case entryResult:
		body := truncateText(strings.TrimRight(e.text, "\n"), 2400)
		if strings.TrimSpace(body) == "" {
			body = "(empty)"
		}
		lines := strings.Split(body, "\n")
		var builder strings.Builder
		for i, line := range lines {
			if i == 0 {
				builder.WriteString(resultStyle.Render("  ⎿ " + line))
				continue
			}
			builder.WriteString("\n" + resultStyle.Render("    "+line))
		}
		return builder.String()
	case entrySystem:
		return dimStyle.Render("  " + wrapText(e.text, width-2))
	}
	return ""
}

func wrapText(text string, width int) string {
	return lipgloss.NewStyle().MaxWidth(maxInt(1, width)).Render(text)
}

func oneLine(text string, width int) string {
	text = strings.ReplaceAll(text, "\n", " ")
	return truncateText(text, maxInt(1, width))
}

func truncateText(text string, limit int) string {
	runes := []rune(text)
	if len(runes) <= limit {
		return text
	}
	return string(runes[:limit]) + "…"
}

func maxInt(a, b int) int {
	if a > b {
		return a
	}
	return b
}
