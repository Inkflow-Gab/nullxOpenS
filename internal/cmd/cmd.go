// Package cmd implements the nullx command line interface.
package cmd

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"

	"github.com/Inkflow-Gab/nullxOpenS/internal/agent"
	"github.com/Inkflow-Gab/nullxOpenS/internal/config"
	"github.com/Inkflow-Gab/nullxOpenS/internal/llm"
	"github.com/Inkflow-Gab/nullxOpenS/internal/session"
	"github.com/Inkflow-Gab/nullxOpenS/internal/tools"
	"github.com/Inkflow-Gab/nullxOpenS/internal/tui"
	"github.com/Inkflow-Gab/nullxOpenS/internal/ui"
)

const version = "0.3.0"

// Run dispatches the command line.
func Run(args []string) error {
	if len(args) == 0 {
		return repl(context.Background(), nil)
	}
	switch args[0] {
	case "run":
		return runOnce(args[1:])
	case "models":
		return listModels(args[1:])
	case "doctor":
		return doctor(args[1:])
	case "init":
		return initialize(args[1:])
	case "config":
		return showConfig(args[1:])
	case "sessions":
		return listSessions(args[1:])
	case "tools":
		return listTools()
	case "gateway":
		return runGateway(args[1:])
	case "version", "-v", "--version":
		fmt.Println("nullx " + version)
		return nil
	case "help", "-h", "--help":
		usage()
		return nil
	}
	if strings.HasPrefix(args[0], "-") {
		usage()
		return nil
	}
	return runOnce(args)
}

func usage() {
	fmt.Print(`nullx — terminal coding agent for an OpenAI-compatible gateway

Usage:
  nullx                       start the interactive shell
  nullx run [prompt...]       run one prompt and exit
  nullx models [-free]        list models from the gateway
  nullx doctor                check the gateway and free-model availability
  nullx init [-force]         write the default configuration
  nullx config                print the configuration path and values
  nullx sessions              list saved sessions
  nullx tools                 list built-in tools
  nullx gateway [flags]       run the opencode2api gateway binary
  nullx version               print the version

Flags for run and the shell:
  -config PATH      configuration file
  -model ID         override the model
  -permission MODE  ask, allow, or deny
`)
}

type options struct {
	configPath string
	model      string
	permission string
}

func parseOptions(name string, args []string) (options, []string, error) {
	flags := flag.NewFlagSet(name, flag.ContinueOnError)
	flags.SetOutput(os.Stderr)
	opts := options{}
	flags.StringVar(&opts.configPath, "config", "", "configuration file")
	flags.StringVar(&opts.model, "model", "", "model ID")
	flags.StringVar(&opts.permission, "permission", "", "ask, allow, or deny")
	if err := flags.Parse(args); err != nil {
		return opts, nil, err
	}
	return opts, flags.Args(), nil
}

func loadConfig(opts options) (config.Config, string, error) {
	path := opts.configPath
	if strings.TrimSpace(path) == "" {
		path = config.Path()
	}
	cfg, err := config.Load(path)
	if err != nil {
		return config.Config{}, path, err
	}
	if strings.TrimSpace(opts.model) != "" {
		cfg.Model = opts.model
	}
	if strings.TrimSpace(opts.permission) != "" {
		cfg.Permission = opts.permission
	}
	if err := cfg.Validate(); err != nil {
		return config.Config{}, path, err
	}
	return cfg, path, nil
}

func build(cfg config.Config, screen *ui.UI, sess *session.Session) *agent.Agent {
	client := llm.New(cfg.BaseURL, cfg.APIKey, time.Duration(cfg.Timeout)*time.Second)
	return agent.New(cfg, client, tools.Builtins(), screen, sess)
}

func repl(ctx context.Context, args []string) error {
	opts, _, err := parseOptions("nullx", args)
	if err != nil {
		return err
	}
	cfg, path, err := loadConfig(opts)
	if err != nil {
		return err
	}
	if err := prepareModel(&cfg); err != nil {
		return err
	}
	screen := ui.New(os.Stdin, os.Stdout)
	sess, err := session.New(filepath.Join(config.DataDir(), "sessions"))
	if err != nil {
		return err
	}
	if screen.Interactive() {
		return tui.Run(cfg, sess, version, path)
	}
	runner := build(cfg, screen, sess)

	screen.Printf("nullx %s — %s via %s", version, cfg.Model, cfg.BaseURL)
	screen.Printf("config: %s", path)
	screen.Printf("session: %s", sess.ID)
	screen.Printf("type /help for commands, /exit to quit")

	for {
		line, err := screen.ReadLine("\n> ")
		if err != nil {
			return nil
		}
		line = strings.TrimSpace(line)
		if line == "" {
			continue
		}
		if strings.HasPrefix(line, "/") {
			done, err := slash(runner, screen, sess, line)
			if err != nil {
				screen.Printf("error: %v", err)
			}
			if done {
				return nil
			}
			continue
		}
		if err := runner.Run(ctx, line); err != nil {
			if errors.Is(err, context.Canceled) {
				return nil
			}
			screen.Printf("error: %v", err)
		}
	}
}

func slash(runner *agent.Agent, screen *ui.UI, sess *session.Session, line string) (bool, error) {
	fields := strings.Fields(line)
	switch fields[0] {
	case "/exit", "/quit":
		return true, nil
	case "/help":
		screen.Printf("/exit  /clear  /model <id>  /tools  /session  /config")
		return false, nil
	case "/clear":
		runner.Reset()
		screen.Printf("conversation cleared")
		return false, nil
	case "/model":
		if len(fields) < 2 {
			screen.Printf("current model: %s", runner.Config.Model)
			return false, nil
		}
		runner.Config.Model = fields[1]
		screen.Printf("model set to %s", runner.Config.Model)
		return false, nil
	case "/tools":
		for _, line := range runner.Tools.Describe() {
			screen.Printf("%s", line)
		}
		return false, nil
	case "/session":
		screen.Printf("session %s (%d messages)", sess.ID, len(sess.Messages))
		return false, nil
	case "/config":
		data, err := json.MarshalIndent(runner.Config.Redacted(), "", "  ")
		if err != nil {
			return false, err
		}
		screen.Printf("%s", string(data))
		return false, nil
	default:
		screen.Printf("unknown command %s", fields[0])
		return false, nil
	}
}

func runOnce(args []string) error {
	opts, rest, err := parseOptions("run", args)
	if err != nil {
		return err
	}
	if len(rest) == 0 {
		return fmt.Errorf("prompt is required")
	}
	cfg, _, err := loadConfig(opts)
	if err != nil {
		return err
	}
	if err := prepareModel(&cfg); err != nil {
		return err
	}
	screen := ui.New(os.Stdin, os.Stdout)
	sess, err := session.New(filepath.Join(config.DataDir(), "sessions"))
	if err != nil {
		return err
	}
	runner := build(cfg, screen, sess)
	return runner.Run(context.Background(), strings.Join(rest, " "))
}

func listModels(args []string) error {
	flags := flag.NewFlagSet("models", flag.ContinueOnError)
	flags.SetOutput(os.Stderr)
	configPath := ""
	freeOnly := false
	flags.StringVar(&configPath, "config", "", "configuration file")
	flags.BoolVar(&freeOnly, "free", false, "list only free models")
	if err := flags.Parse(args); err != nil {
		return err
	}
	cfg, err := config.Load(configPath)
	if err != nil {
		return err
	}
	client := llm.New(cfg.BaseURL, cfg.APIKey, time.Duration(cfg.Timeout)*time.Second)
	ctx, cancel := context.WithTimeout(context.Background(), time.Duration(cfg.Timeout)*time.Second)
	defer cancel()
	models, err := client.Models(ctx)
	if err != nil {
		return err
	}
	shown := 0
	for _, model := range models {
		if freeOnly && !model.IsFree() {
			continue
		}
		marker := "     "
		if model.IsFree() {
			marker = "[free]"
		}
		if model.ContextWindow > 0 {
			fmt.Printf("%s %-44s context=%d\n", marker, model.ID, model.ContextWindow)
		} else {
			fmt.Printf("%s %s\n", marker, model.ID)
		}
		shown++
	}
	if shown == 0 {
		fmt.Println("(no models matched)")
	}
	return nil
}

// prepareModel resolves an "auto" (or empty) model to the first free model the
// gateway advertises, so a fresh install works against the anonymous lane.
func prepareModel(cfg *config.Config) error {
	if strings.TrimSpace(cfg.Model) != "" && !strings.EqualFold(cfg.Model, "auto") {
		return nil
	}
	client := llm.New(cfg.BaseURL, cfg.APIKey, time.Duration(cfg.Timeout)*time.Second)
	ctx, cancel := context.WithTimeout(context.Background(), time.Duration(cfg.Timeout)*time.Second)
	defer cancel()
	models, err := client.Models(ctx)
	if err != nil {
		return fmt.Errorf("list models: %w", err)
	}
	chosen, ok := llm.ResolveModel(models, cfg.Model)
	if !ok {
		return fmt.Errorf("the gateway returned no models")
	}
	cfg.Model = chosen.ID
	return nil
}

// doctor checks the gateway, its credentials, and whether free models are
// reachable.
func doctor(args []string) error {
	flags := flag.NewFlagSet("doctor", flag.ContinueOnError)
	flags.SetOutput(os.Stderr)
	configPath := ""
	probe := true
	flags.StringVar(&configPath, "config", "", "configuration file")
	flags.BoolVar(&probe, "probe", true, "send a tiny completion to the selected model")
	if err := flags.Parse(args); err != nil {
		return err
	}
	cfg, err := config.Load(configPath)
	if err != nil {
		return err
	}
	client := llm.New(cfg.BaseURL, cfg.APIKey, time.Duration(cfg.Timeout)*time.Second)
	ctx, cancel := context.WithTimeout(context.Background(), time.Duration(cfg.Timeout)*time.Second)
	defer cancel()

	fmt.Printf("gateway: %s\n", cfg.BaseURL)
	fmt.Printf("api key: %s\n", keyStatus(cfg.APIKey))

	health, healthErr := client.Health(ctx)
	if healthErr != nil {
		fmt.Printf("health: FAIL (%v)\n", healthErr)
	} else {
		status, _ := health["status"].(string)
		ready, _ := health["ready"].(bool)
		fmt.Printf("health: %s (ready=%v)\n", status, ready)
		if keys, ok := health["keys"].(map[string]any); ok {
			fmt.Printf("keys: zen=%v go=%v anonymous=%v\n", keys["zen"], keys["go"], keys["anonymous"])
		}
		if issues, ok := health["issues"].([]any); ok && len(issues) > 0 {
			fmt.Printf("issues: %v\n", issues)
		}
	}

	models, modelErr := client.Models(ctx)
	if modelErr != nil {
		fmt.Printf("models: FAIL (%v)\n", modelErr)
		return fmt.Errorf("cannot list models: %w", modelErr)
	}
	free := 0
	for _, model := range models {
		if model.IsFree() {
			free++
		}
	}
	fmt.Printf("models: %d total, %d free\n", len(models), free)
	chosen, ok := llm.ResolveModel(models, cfg.Model)
	if !ok {
		return fmt.Errorf("no models available")
	}
	fmt.Printf("selected model: %s (free=%v)\n", chosen.ID, chosen.IsFree())
	if free == 0 {
		return fmt.Errorf("no free models advertised; enable anonymous or add free-model keys in the gateway config")
	}
	if probe {
		probeCtx, cancel := context.WithTimeout(ctx, 60*time.Second)
		defer cancel()
		start := time.Now()
		_, err := client.Stream(probeCtx, llm.ChatRequest{
			Model:       chosen.ID,
			Messages:    []llm.Message{{Role: "user", Content: "Reply with OK."}},
			MaxTokens:   16,
			Temperature: 0,
		}, nil, nil)
		if err != nil {
			fmt.Printf("inference: FAIL (%v)\n", err)
			return fmt.Errorf("selected free model did not answer: %w", err)
		}
		fmt.Printf("inference: OK (%s)\n", time.Since(start).Round(time.Millisecond))
	}
	return nil
}

func keyStatus(key string) string {
	if strings.TrimSpace(key) == "" {
		return "(unset)"
	}
	return config.Mask(key)
}

func initialize(args []string) error {
	flags := flag.NewFlagSet("init", flag.ContinueOnError)
	flags.SetOutput(os.Stderr)
	path := ""
	force := false
	flags.StringVar(&path, "config", "", "configuration file")
	flags.BoolVar(&force, "force", false, "overwrite an existing file")
	if err := flags.Parse(args); err != nil {
		return err
	}
	if strings.TrimSpace(path) == "" {
		path = config.Path()
	}
	if !force {
		if _, err := os.Stat(path); err == nil {
			return fmt.Errorf("%s already exists (use -force to overwrite)", path)
		}
	}
	if err := config.Save(path, config.Default()); err != nil {
		return err
	}
	fmt.Printf("wrote %s\n", path)
	return nil
}

func showConfig(args []string) error {
	opts, _, err := parseOptions("config", args)
	if err != nil {
		return err
	}
	path := opts.configPath
	if strings.TrimSpace(path) == "" {
		path = config.Path()
	}
	cfg, err := config.Load(path)
	if err != nil {
		return err
	}
	data, err := json.MarshalIndent(cfg.Redacted(), "", "  ")
	if err != nil {
		return err
	}
	fmt.Printf("# %s\n%s\n", path, data)
	return nil
}

func listSessions(args []string) error {
	if _, _, err := parseOptions("sessions", args); err != nil {
		return err
	}
	dir := filepath.Join(config.DataDir(), "sessions")
	metas, err := session.List(dir)
	if err != nil {
		return err
	}
	if len(metas) == 0 {
		fmt.Println("(no sessions)")
		return nil
	}
	for _, meta := range metas {
		fmt.Printf("%s  %s  %d messages\n", meta.ID, meta.Created.Local().Format("2006-01-02 15:04"), meta.Messages)
	}
	return nil
}

func listTools() error {
	for _, line := range tools.Builtins().Describe() {
		fmt.Println(line)
	}
	return nil
}

func runGateway(args []string) error {
	flags := flag.NewFlagSet("gateway", flag.ContinueOnError)
	flags.SetOutput(os.Stderr)
	binary := ""
	configPath := ""
	flags.StringVar(&binary, "bin", "", "gateway binary (default from config)")
	flags.StringVar(&configPath, "config", "", "gateway configuration file")
	if err := flags.Parse(args); err != nil {
		return err
	}
	cfg, _, err := loadConfig(options{})
	if err != nil {
		return err
	}
	if strings.TrimSpace(binary) == "" {
		binary = cfg.GatewayBin
	}
	if strings.TrimSpace(configPath) == "" {
		configPath = cfg.GatewayConfig
	}
	command := exec.Command(binary, "-config", configPath)
	command.Stdin = os.Stdin
	command.Stdout = os.Stdout
	command.Stderr = os.Stderr
	fmt.Printf("starting %s -config %s\n", binary, configPath)
	return command.Run()
}
