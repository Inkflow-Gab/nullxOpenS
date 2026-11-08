// Package tui implements the full-screen Bubble Tea interface.
package tui

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
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
	accentStyle   = lipgloss.NewStyle().Foreground(lipgloss.Color("212")).Bold(true)
	userStyle     = lipgloss.NewStyle().Foreground(lipgloss.Color("39")).Bold(true)
	dimStyle      = lipgloss.NewStyle().Foreground(lipgloss.Color("241"))
	toolStyle     = lipgloss.NewStyle().Foreground(lipgloss.Color("214")).Bold(true)
	resultStyle   = lipgloss.NewStyle().Foreground(lipgloss.Color("245"))
	thinkingStyle = lipgloss.NewStyle().Foreground(lipgloss.Color("243")).Italic(true)
	goodStyle     = lipgloss.NewStyle().Foreground(lipgloss.Color("42")).Bold(true)
	badStyle      = lipgloss.NewStyle().Foreground(lipgloss.Color("203")).Bold(true)
	inputStyle    = lipgloss.NewStyle().
			Border(lipgloss.RoundedBorder()).
			BorderForeground(lipgloss.Color("62")).
			Padding(0, 1)
	askStyle = inputStyle.BorderForeground(lipgloss.Color("214"))
)

type entryKind int

const (
	entryUser entryKind = iota
	entryAssistant
	entryThinking
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
	evReasoning
	evNewline
	evPrint
	evToolStart
	evToolResult
	evBilling
	evAsk
)

type event struct {
	kind     eventKind
	name     string
	text     string
	question string
	source   string
	cost     float64
	free     bool
	known    bool
	reply    chan bool
}

type runDoneMsg struct {
	err error
}

type compactDoneMsg struct {
	summary string
	err     error
}

type modelsDoneMsg struct {
	models []llm.ModelInfo
	err    error
}

type editorDoneMsg struct {
	text string
	err  error
}

type healthMsg struct {
	document map[string]any
	err      error
}

type healthTickMsg struct{}

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
	think   strings.Builder
	pending strings.Builder
	last    time.Time

	showThinking bool
	healthText   string
	healthOK     bool
	freeModels   int
	totalModels  int
	warpText     string
	billingText  string

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
		showThinking: true,
		healthText:   "checking…",
		warpText:     "warp ?",
		billingText:  "free-tier: ?",
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
	return tea.Batch(textarea.Blink, m.spin.Tick, m.checkHealth())
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

// Reasoning implements ui.Sink.
func (m *Model) Reasoning(text string) {
	if text == "" {
		return
	}
	m.emit(event{kind: evReasoning, text: text})
}

// Billing implements ui.Sink.
func (m *Model) Billing(source string, free bool, cost float64, known bool) {
	m.emit(event{kind: evBilling, source: source, free: free, cost: cost, known: known})
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
	case healthTickMsg:
		return m, m.checkHealth()
	case healthMsg:
		m.applyHealth(msg)
		return m, tea.Tick(15*time.Second, func(time.Time) tea.Msg { return healthTickMsg{} })
	case runDoneMsg:
		m.busy = false
		m.cancel = nil
		if m.think.Len() > 0 {
			m.addEntry(entry{kind: entryThinking, text: m.think.String()})
			m.think.Reset()
		}
		if m.stream.Len() > 0 {
			m.addEntry(entry{kind: entryAssistant, text: m.stream.String()})
			m.stream.Reset()
		}
		if msg.err != nil {
			if errors.Is(msg.err, context.Canceled) {
				m.addSystem("interrupted")
			} else {
				m.addSystem("error: " + msg.err.Error())
				text := strings.ToLower(msg.err.Error())
				if strings.Contains(text, "free tier") || strings.Contains(text, "rate limit") ||
					strings.Contains(text, "429") || strings.Contains(text, "quota") {
					m.billingText = "free-tier: BLOCKED"
				}
			}
		}
		m.relayout()
		return m, nil
	case compactDoneMsg:
		m.busy = false
		m.cancel = nil
		if msg.err != nil {
			m.addSystem("compact failed: " + msg.err.Error())
		} else {
			m.rebuildHistory()
			m.addSystem(fmt.Sprintf("conversation compacted to a %d-character summary", len(msg.summary)))
		}
		m.relayout()
		return m, nil
	case modelsDoneMsg:
		if msg.err != nil {
			m.addSystem("models failed: " + msg.err.Error())
		} else {
			for _, model := range msg.models {
				marker := "    "
				if model.IsFree() {
					marker = "[free]"
				}
				m.addSystem(fmt.Sprintf("%s %s  context=%d", marker, model.ID, model.ContextWindow))
			}
		}
		m.relayout()
		return m, nil
	case editorDoneMsg:
		if msg.err != nil {
			m.addSystem("editor failed: " + msg.err.Error())
			return m, nil
		}
		m.input.SetValue(msg.text)
		m.input.Focus()
		m.resizeInput()
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
	case evReasoning:
		m.think.WriteString(ev.text)
		m.refresh()
	case evBilling:
		if ev.known {
			if ev.free {
				m.billingText = "free-tier: OK"
			} else if ev.cost > 0 {
				m.billingText = fmt.Sprintf("free-tier: PAID $%.4f", ev.cost)
			} else {
				m.billingText = "free-tier: OK"
			}
		}
		m.refresh()
	case evNewline:
		if m.think.Len() > 0 {
			m.addEntry(entry{kind: entryThinking, text: m.think.String()})
			m.think.Reset()
		}
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
	case "ctrl+t":
		m.showThinking = !m.showThinking
		if m.showThinking {
			m.addSystem("thinking expanded")
		} else {
			m.addSystem("thinking collapsed")
		}
		m.relayout()
		return m, nil
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
		return m.startPrompt(value)
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

func (m *Model) startPrompt(value string) (tea.Model, tea.Cmd) {
	m.addEntry(entry{kind: entryUser, text: value})
	m.busy = true
	m.stream.Reset()
	m.think.Reset()
	ctx, cancel := context.WithCancel(context.Background())
	m.cancel = cancel
	runner := m.runner
	m.relayout()
	return m, tea.Batch(
		func() tea.Msg { return runDoneMsg{err: runner.Run(ctx, value)} },
		m.spin.Tick,
	)
}

func (m *Model) checkHealth() tea.Cmd {
	client := m.runner.Client
	return func() tea.Msg {
		ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		document, err := client.Health(ctx)
		return healthMsg{document: document, err: err}
	}
}

func (m *Model) applyHealth(message healthMsg) {
	if message.err != nil {
		m.healthOK = false
		m.healthText = "gateway down"
		return
	}
	status := asString(message.document["status"])
	if status == "" {
		status = "?"
	}
	ready, _ := message.document["ready"].(bool)
	m.healthOK = ready || status == "ok" || status == "ready"

	if models, ok := message.document["models"].(map[string]any); ok {
		m.freeModels = asInt(models["exposed"])
		m.totalModels = asInt(models["total"])
	}
	if warp, ok := message.document["warp"].(map[string]any); ok {
		m.warpText = "warp " + asString(warp["status"])
		if active := asInt(warp["active"]); active > 0 {
			m.warpText += fmt.Sprintf(" %d", active)
		}
	}
	m.healthText = fmt.Sprintf("%s · %d free/%d", status, m.freeModels, m.totalModels)
}

func (m *Model) handleSlash(line string) (tea.Model, tea.Cmd) {
	fields := strings.Fields(line)
	switch fields[0] {
	case "/exit", "/quit":
		m.stop()
		return m, tea.Quit
	case "/help":
		for _, text := range []string{
			"/init          analyze the repo and write AGENTS.md",
			"/new, /clear   start a fresh conversation",
			"/compact       summarize the conversation",
			"/undo, /redo   rewind or restore the last turn",
			"/models         list gateway models",
			"/model <id>    switch model",
			"/thinking <m>  none, minimal, low, medium, high, xhigh, max",
			"/details       expand or collapse thinking",
			"/status        gateway, free-tier, session state",
			"/sessions      list saved sessions",
			"/export [p]    write the conversation as Markdown",
			"/editor        compose the prompt in $EDITOR",
			"/tools         list built-in tools",
			"/session       show the session id",
			"/config        show the active config",
			"/share         show the session file path",
			"/exit          quit",
			"",
			"enter send · alt+enter newline · ctrl+t thinking · pgup/pgdn scroll · ctrl+c interrupt",
		} {
			m.addSystem(text)
		}
	case "/new", "/clear":
		m.runner.Reset()
		m.entries = nil
		m.stream.Reset()
		m.think.Reset()
		m.addSystem("new conversation")
	case "/init":
		return m.startPrompt("Analyze this repository and create or update AGENTS.md. " +
			"Inspect the tree first, then write the build, test, run, architecture, and convention notes a coding agent needs.")
	case "/compact":
		if m.busy {
			return m, nil
		}
		ctx, cancel := context.WithCancel(context.Background())
		m.cancel = cancel
		m.busy = true
		runner := m.runner
		m.relayout()
		return m, tea.Batch(func() tea.Msg {
			summary, err := runner.Compact(ctx)
			return compactDoneMsg{summary: summary, err: err}
		}, m.spin.Tick)
	case "/undo":
		if m.runner.Undo() {
			m.rebuildHistory()
			m.addSystem(fmt.Sprintf("undid the last turn · %d messages remain", m.runner.HistoryCount()))
		} else {
			m.addSystem("nothing to undo")
		}
	case "/redo":
		if m.runner.Redo() {
			m.rebuildHistory()
			m.addSystem("restored the last turn")
		} else {
			m.addSystem("nothing to redo")
		}
	case "/models":
		client := m.runner.Client
		return m, func() tea.Msg {
			ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
			defer cancel()
			models, err := client.Models(ctx)
			return modelsDoneMsg{models: models, err: err}
		}
	case "/model":
		if len(fields) < 2 {
			m.addSystem("current model: " + m.runner.Config.Model)
			break
		}
		m.runner.Config.Model = fields[1]
		m.cfg.Model = fields[1]
		m.addSystem("model set to " + fields[1])
	case "/thinking", "/effort":
		if len(fields) < 2 {
			m.addSystem("reasoning effort: " + valueOr(m.runner.Config.ReasoningEffort, "none"))
			break
		}
		mode := strings.ToLower(fields[1])
		valid := false
		switch mode {
		case "none", "minimal", "low", "medium", "high", "xhigh", "max":
			valid = true
		}
		if !valid {
			m.addSystem("effort must be none, minimal, low, medium, high, xhigh, or max")
			break
		}
		m.runner.Config.ReasoningEffort = mode
		m.cfg.ReasoningEffort = mode
		m.addSystem("reasoning effort set to " + mode)
	case "/details":
		m.showThinking = !m.showThinking
		if m.showThinking {
			m.addSystem("thinking expanded")
		} else {
			m.addSystem("thinking collapsed")
		}
	case "/status":
		for _, text := range []string{
			"gateway: " + m.healthText,
			"warp: " + m.warpText,
			m.billingText,
			"model: " + m.runner.Config.Model,
			"effort: " + valueOr(m.runner.Config.ReasoningEffort, "none"),
			"permission: " + m.runner.Config.Permission,
			fmt.Sprintf("session: %s · %d messages", m.sess.ID, m.runner.HistoryCount()),
		} {
			m.addSystem(text)
		}
	case "/sessions":
		metas, err := session.List(filepath.Join(config.DataDir(), "sessions"))
		if err != nil {
			m.addSystem("sessions failed: " + err.Error())
			break
		}
		if len(metas) == 0 {
			m.addSystem("(no saved sessions)")
			break
		}
		for _, meta := range metas {
			m.addSystem(fmt.Sprintf("%s  %s  %d messages", meta.ID, meta.Created.Local().Format("2006-01-02 15:04"), meta.Messages))
		}
	case "/export":
		path := fmt.Sprintf("nullx-%s.md", m.sess.ID)
		if len(fields) > 1 {
			path = fields[1]
		}
		if err := m.runner.Export(path); err != nil {
			m.addSystem("export failed: " + err.Error())
		} else {
			m.addSystem("exported to " + path)
		}
	case "/editor":
		editor := strings.TrimSpace(os.Getenv("EDITOR"))
		if editor == "" {
			editor = "vi"
		}
		file, err := os.CreateTemp("", "nullx-*.md")
		if err != nil {
			m.addSystem("editor failed: " + err.Error())
			break
		}
		path := file.Name()
		_, writeErr := file.WriteString(m.input.Value())
		file.Close()
		if writeErr != nil {
			os.Remove(path)
			m.addSystem("editor failed: " + writeErr.Error())
			break
		}
		return m, tea.ExecProcess(exec.Command(editor, path), func(err error) tea.Msg {
			data, readErr := os.ReadFile(path)
			os.Remove(path)
			if err == nil {
				err = readErr
			}
			return editorDoneMsg{text: string(data), err: err}
		})
	case "/tools":
		for _, text := range m.runner.Tools.Describe() {
			m.addSystem(text)
		}
	case "/session":
		m.addSystem(fmt.Sprintf("session %s · %d messages", m.sess.ID, m.runner.HistoryCount()))
	case "/share":
		m.addSystem(filepath.Join(config.DataDir(), "sessions", m.sess.ID+".json"))
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

func (m *Model) rebuildHistory() {
	m.entries = nil
	for _, message := range m.runner.History() {
		switch message.Role {
		case "user":
			if message.Content != "" {
				m.entries = append(m.entries, entry{kind: entryUser, text: message.Content})
			}
		case "assistant":
			if message.Content != "" {
				m.entries = append(m.entries, entry{kind: entryAssistant, text: message.Content})
			}
			for _, call := range message.ToolCalls {
				m.entries = append(m.entries, entry{kind: entryTool, name: call.Function.Name, text: call.Function.Arguments})
			}
		case "tool":
			m.entries = append(m.entries, entry{kind: entryResult, text: message.Content})
		}
	}
	m.stream.Reset()
	m.think.Reset()
	m.refresh()
	m.relayout()
}

func valueOr(value, fallback string) string {
	if strings.TrimSpace(value) == "" {
		return fallback
	}
	return value
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
	healthStyle := goodStyle
	if !m.healthOK {
		healthStyle = badStyle
	}
	line := healthStyle.Render("● ") + dimStyle.Render("gateway "+m.healthText)
	if m.busy {
		line = " " + m.spin.View() + " " + line
	}
	billingStyle := goodStyle
	switch {
	case strings.Contains(m.billingText, "BLOCKED"), strings.Contains(m.billingText, "PAID"):
		billingStyle = badStyle
	case strings.Contains(m.billingText, "?"):
		billingStyle = dimStyle
	}
	line += dimStyle.Render(" · ") + billingStyle.Render(m.billingText) +
		dimStyle.Render(" · "+m.warpText)
	left := dimStyle.Render("enter send · alt+enter newline · ctrl+t think · /help")
	right := dimStyle.Render("perm:" + m.cfg.Permission)
	gap := width - lipgloss.Width(left) - lipgloss.Width(right)
	if gap > 0 {
		left += strings.Repeat(" ", gap) + right
	}
	return line + "\n" + left
}

func (m *Model) render() string {
	width := maxInt(20, m.view.Width)
	var builder strings.Builder
	for _, e := range m.entries {
		builder.WriteString(m.renderEntry(e, width))
		builder.WriteString("\n")
	}
	if m.think.Len() > 0 {
		builder.WriteString(m.renderEntry(entry{kind: entryThinking, text: m.think.String()}, width))
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
	case entryThinking:
		if !m.showThinking {
			lines := strings.Count(strings.TrimSpace(e.text), "\n") + 1
			return dimStyle.Render(fmt.Sprintf("▸ thinking · %d lines · ctrl+t", lines))
		}
		body := strings.ReplaceAll(wrapText(e.text, width-4), "\n", "\n  ")
		return dimStyle.Render("▾ thinking") + "\n" + thinkingStyle.Render("  "+body)
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

func asString(value any) string {
	text, _ := value.(string)
	return text
}

func asInt(value any) int {
	switch number := value.(type) {
	case float64:
		return int(number)
	case int:
		return number
	case int64:
		return int(number)
	}
	return 0
}
