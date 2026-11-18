package config

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"
)

// Rotation is the free-lane rotation state the OpenCode UNLIMITED controller
// persists next to the gateway configuration. The gateway itself has no
// rotation endpoint, so this file is how the agent learns whether the free
// allowance is following the address or has walled the whole pool.
type Rotation struct {
	Blocks    int
	Successes int
	Scopes    []string

	// Wall is open when two different egress scopes were refused in a row,
	// which means a fresh address does not clear the allowance and only the
	// daily reset does.
	WallOpen   bool
	WallUntil  time.Time
	WallReason string
	WallSince  time.Time

	LastBlock   time.Time
	LastSuccess time.Time
}

// Known reports whether a state file was found and read.
func (r Rotation) Known() bool {
	return r.LastBlock != (time.Time{}) || r.Blocks > 0 || r.WallOpen
}

// RotationFile is where the controller keeps the rotation state.
func RotationFile() string {
	home, err := os.UserHomeDir()
	if err != nil || home == "" {
		return ""
	}
	return filepath.Join(home, ".opencode-proxy", "rotation.json")
}

// LoadRotation reads the persisted rotation state. A missing file is not an
// error: a fresh install has simply never hit a wall.
func LoadRotation() (Rotation, bool) {
	path := RotationFile()
	if path == "" {
		return Rotation{}, false
	}
	data, err := os.ReadFile(path)
	if err != nil {
		return Rotation{}, false
	}
	var document struct {
		Blocks    int     `json:"blocks"`
		Successes int     `json:"successes"`
		LastBlock float64 `json:"last_block"`
		Scopes    map[string]struct {
			Last float64 `json:"last"`
		} `json:"scopes"`
		Wall struct {
			Open      bool    `json:"open"`
			Until     float64 `json:"until"`
			Since     float64 `json:"since"`
			Reason    string  `json:"reason"`
			ClearedAt float64 `json:"cleared_at"`
		} `json:"wall"`
		LastSuccess float64 `json:"last_success"`
	}
	if err := json.Unmarshal(data, &document); err != nil {
		return Rotation{}, false
	}
	rotation := Rotation{
		Blocks:      document.Blocks,
		Successes:   document.Successes,
		LastBlock:   unixTime(document.LastBlock),
		LastSuccess: unixTime(document.LastSuccess),
		WallOpen:    document.Wall.Open,
		WallUntil:   unixTime(document.Wall.Until),
		WallSince:   unixTime(document.Wall.Since),
		WallReason:  strings.TrimSpace(document.Wall.Reason),
	}
	for scope := range document.Scopes {
		rotation.Scopes = append(rotation.Scopes, scope)
	}
	return rotation, true
}

// WallReset is the local clock of the next allowance reset.
func (r Rotation) WallReset() string {
	if r.WallUntil.IsZero() {
		return ""
	}
	return r.WallUntil.UTC().Format("15:04 UTC") + " (" + r.WallUntil.Local().Format("15:04") + " your time)"
}

// Summary is one line about the free wall, empty when nothing is wrong.
func (r Rotation) Summary() string {
	switch {
	case r.WallOpen:
		reset := r.WallReset()
		if reset == "" {
			return "paused until the daily reset"
		}
		return "paused until " + reset
	case r.Blocks > 0 && time.Since(r.LastBlock) < 30*time.Minute && !r.LastSuccess.After(r.LastBlock):
		return "rotating, " + strconv.Itoa(r.Blocks) + " exit(s) refused"
	}
	return ""
}

// Hint explains an open wall in the words the agent uses elsewhere.
func (r Rotation) Hint() string {
	if !r.WallOpen {
		return ""
	}
	if reset := r.WallReset(); reset != "" {
		return "the free allowance is not following the address, so every exit gets refused. It resets at " + reset + ". Rotating again will not help; use another provider or wait for the reset."
	}
	return "the free allowance is not following the address, so every exit gets refused. Rotating again will not help; use another provider or wait for the daily reset."
}

func unixTime(value float64) time.Time {
	if value <= 0 {
		return time.Time{}
	}
	seconds, fraction := int64(value), value-float64(int64(value))
	return time.Unix(seconds, int64(fraction*float64(time.Second))).UTC()
}
