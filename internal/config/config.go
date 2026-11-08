// Package config loads and stores the nullx configuration.
package config

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

// Permission modes for tool execution.
const (
	PermissionAsk   = "ask"
	PermissionAllow = "allow"
	PermissionDeny  = "deny"
)

// Config is the nullx configuration stored in config.json.
type Config struct {
	BaseURL         string   `json:"base_url"`
	APIKey          string   `json:"api_key"`
	Model           string   `json:"model"`
	SystemPrompt    string   `json:"system_prompt,omitempty"`
	MaxTokens       int      `json:"max_tokens"`
	Temperature     float64  `json:"temperature"`
	ReasoningEffort string   `json:"reasoning_effort,omitempty"`
	MaxSteps        int      `json:"max_steps"`
	Timeout         int      `json:"timeout_seconds"`
	Permission      string   `json:"permission"`
	ContextFiles    []string `json:"context_files"`
	GatewayBin      string   `json:"gateway_bin,omitempty"`
	GatewayConfig   string   `json:"gateway_config,omitempty"`
}

// Default returns the built-in configuration, with environment overrides
// applied for the connection fields and the OpenCode UNLIMITED installer
// discovered when it is present.
func Default() Config {
	baseURL := envOr("NULLX_BASE_URL", "http://127.0.0.1:8080/v1")
	gatewayBin, gatewayConfig := discoverGateway()
	return Config{
		BaseURL:         baseURL,
		APIKey:          envOr("NULLX_API_KEY", discoverAPIKey(baseURL)),
		Model:           envOr("NULLX_MODEL", "auto"),
		MaxTokens:       8192,
		Temperature:     0.2,
		ReasoningEffort: envOr("NULLX_REASONING_EFFORT", "low"),
		MaxSteps:        40,
		Timeout:         300,
		Permission:      PermissionAsk,
		ContextFiles:    []string{"AGENTS.md", "CLAUDE.md", "GEMINI.md", "NULLX.md", ".nullx.md"},
		GatewayBin:      envOr("NULLX_GATEWAY_BIN", gatewayBin),
		GatewayConfig:   envOr("NULLX_GATEWAY_CONFIG", gatewayConfig),
	}
}

func envOr(name, fallback string) string {
	if value := strings.TrimSpace(os.Getenv(name)); value != "" {
		return value
	}
	return fallback
}

// gatewayConfigPaths lists the opencode2api configuration files the OpenCode
// UNLIMITED installer writes, most specific first.
func gatewayConfigPaths() []string {
	home, err := os.UserHomeDir()
	if err != nil || home == "" {
		return []string{"config.json"}
	}
	return []string{
		filepath.Join(home, ".opencode-proxy", "config.json"),
		filepath.Join(home, ".config", "opencode2api", "config.json"),
		"config.json",
	}
}

// discoverAPIKey reuses the first server key of an installed gateway config so
// nullx talks to a local opencode2api without a second key to configure. The
// discovered key is only used for a loopback base URL.
func discoverAPIKey(baseURL string) string {
	if !isLoopbackURL(baseURL) {
		return ""
	}
	for _, path := range gatewayConfigPaths() {
		data, err := os.ReadFile(path)
		if err != nil {
			continue
		}
		var document struct {
			ServerKeys []string `json:"server_keys"`
		}
		if json.Unmarshal(data, &document) != nil {
			continue
		}
		for _, key := range document.ServerKeys {
			if key = strings.TrimSpace(key); key != "" {
				return key
			}
		}
	}
	return ""
}

// discoverGateway finds the binary and config the OpenCode UNLIMITED installer
// leaves in the home directory, falling back to the PATH name.
func discoverGateway() (binary, configPath string) {
	binary, configPath = "opencode2api", "config.json"
	home, err := os.UserHomeDir()
	if err != nil || home == "" {
		return binary, configPath
	}
	installedBin := filepath.Join(home, ".opencode-proxy", "bin", "opencode2api")
	if info, err := os.Stat(installedBin); err == nil && !info.IsDir() {
		binary = installedBin
	}
	installedConfig := filepath.Join(home, ".opencode-proxy", "config.json")
	if info, err := os.Stat(installedConfig); err == nil && !info.IsDir() {
		configPath = installedConfig
	}
	return binary, configPath
}

// isLoopbackURL reports whether raw points at this machine, where reusing the
// gateway's local key is safe.
func isLoopbackURL(raw string) bool {
	lower := strings.ToLower(strings.TrimSpace(raw))
	return strings.HasPrefix(lower, "http://127.0.0.1") ||
		strings.HasPrefix(lower, "http://localhost") ||
		strings.HasPrefix(lower, "http://[::1]")
}

// Path returns the configuration file path: NULLX_CONFIG, or
// <user-config-dir>/nullx/config.json.
func Path() string {
	if value := strings.TrimSpace(os.Getenv("NULLX_CONFIG")); value != "" {
		return value
	}
	base, err := os.UserConfigDir()
	if err != nil {
		return "nullx.json"
	}
	return filepath.Join(base, "nullx", "config.json")
}

// DataDir returns the directory for sessions: NULLX_DATA, or
// <user-config-dir>/nullx.
func DataDir() string {
	if value := strings.TrimSpace(os.Getenv("NULLX_DATA")); value != "" {
		return value
	}
	base, err := os.UserConfigDir()
	if err != nil {
		return "nullx-data"
	}
	return filepath.Join(base, "nullx")
}

// Load reads the configuration at path, filling defaults for omitted fields.
// A missing file returns the defaults rather than an error.
func Load(path string) (Config, error) {
	if strings.TrimSpace(path) == "" {
		path = Path()
	}
	cfg := Default()
	data, err := os.ReadFile(path)
	if errors.Is(err, os.ErrNotExist) {
		return cfg, nil
	}
	if err != nil {
		return Config{}, fmt.Errorf("read %s: %w", path, err)
	}
	if err := json.Unmarshal(data, &cfg); err != nil {
		return Config{}, fmt.Errorf("parse %s: %w", path, err)
	}
	cfg.applyDefaults()
	if err := cfg.Validate(); err != nil {
		return Config{}, err
	}
	return cfg, nil
}

func (c *Config) applyDefaults() {
	d := Default()
	if strings.TrimSpace(c.BaseURL) == "" {
		c.BaseURL = d.BaseURL
	}
	if strings.TrimSpace(c.APIKey) == "" {
		c.APIKey = d.APIKey
	}
	if strings.TrimSpace(c.Model) == "" {
		c.Model = d.Model
	}
	if c.MaxTokens <= 0 {
		c.MaxTokens = d.MaxTokens
	}
	if strings.TrimSpace(c.ReasoningEffort) == "" {
		c.ReasoningEffort = d.ReasoningEffort
	}
	if c.MaxSteps <= 0 {
		c.MaxSteps = d.MaxSteps
	}
	if c.Timeout <= 0 {
		c.Timeout = d.Timeout
	}
	if strings.TrimSpace(c.Permission) == "" {
		c.Permission = d.Permission
	}
	if len(c.ContextFiles) == 0 {
		c.ContextFiles = d.ContextFiles
	}
	if strings.TrimSpace(c.GatewayBin) == "" {
		c.GatewayBin = d.GatewayBin
	}
	if strings.TrimSpace(c.GatewayConfig) == "" {
		c.GatewayConfig = d.GatewayConfig
	}
}

// Validate rejects values the agent cannot run with.
func (c Config) Validate() error {
	switch c.Permission {
	case PermissionAsk, PermissionAllow, PermissionDeny:
	default:
		return fmt.Errorf("permission must be ask, allow, or deny")
	}
	if c.MaxTokens < 1 {
		return fmt.Errorf("max_tokens must be positive")
	}
	if c.MaxSteps < 1 {
		return fmt.Errorf("max_steps must be positive")
	}
	switch strings.ToLower(c.ReasoningEffort) {
	case "", "none", "minimal", "low", "medium", "high", "xhigh", "max":
	default:
		return fmt.Errorf("reasoning_effort must be none, minimal, low, medium, high, xhigh, or max")
	}
	if c.Timeout < 1 {
		return fmt.Errorf("timeout_seconds must be positive")
	}
	if !strings.HasPrefix(c.BaseURL, "http://") && !strings.HasPrefix(c.BaseURL, "https://") {
		return fmt.Errorf("base_url must be an http or https URL")
	}
	return nil
}

// Save writes cfg to path as indented JSON with owner-only permissions.
func Save(path string, cfg Config) error {
	if strings.TrimSpace(path) == "" {
		path = Path()
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return err
	}
	data, err := json.MarshalIndent(cfg, "", "  ")
	if err != nil {
		return err
	}
	data = append(data, '\n')
	return os.WriteFile(path, data, 0o600)
}

// Redacted returns a copy safe to print: the API key is masked.
func (c Config) Redacted() Config {
	if c.APIKey != "" {
		c.APIKey = Mask(c.APIKey)
	}
	return c
}

// Mask hides all but the last four characters of a secret.
func Mask(value string) string {
	runes := []rune(value)
	if len(runes) <= 6 {
		return "****"
	}
	return "****" + string(runes[len(runes)-4:])
}
