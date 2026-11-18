package config

import (
	"os"
	"path/filepath"
	"strconv"
	"testing"
	"time"
)

func writeRotation(t *testing.T, body string) {
	t.Helper()
	home := t.TempDir()
	t.Setenv("HOME", home)
	dir := filepath.Join(home, ".opencode-proxy")
	if err := os.MkdirAll(dir, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, "rotation.json"), []byte(body), 0o644); err != nil {
		t.Fatal(err)
	}
}

func TestLoadRotation(t *testing.T) {
	until := time.Now().Add(6 * time.Hour).UTC().Truncate(time.Second)
	writeRotation(t, `{
		"blocks": 4,
		"successes": 1,
		"last_block": 1795011240.5,
		"last_success": 1795011300,
		"scopes": {
			"warp:2606:4700:110:8a1c::/64": {"last": 1795011240.5},
			"warp:2606:4700:120:9b2d::/64": {"last": 1795011200}
		},
		"wall": {"open": true, "until": `+formatUnix(until)+`, "since": 1795011200, "reason": "two addresses refused"}
	}`)

	rotation, ok := LoadRotation()
	if !ok {
		t.Fatal("state file was not read")
	}
	if !rotation.Known() || !rotation.WallOpen {
		t.Fatalf("unexpected state: %+v", rotation)
	}
	if rotation.Blocks != 4 || rotation.Successes != 1 || len(rotation.Scopes) != 2 {
		t.Fatalf("unexpected counters: %+v", rotation)
	}
	if !rotation.WallUntil.Equal(until) {
		t.Fatalf("wall until = %v, want %v", rotation.WallUntil, until)
	}
	if rotation.LastBlock.IsZero() {
		t.Fatal("last block was not parsed")
	}
	if rotation.Summary() == "" || rotation.Hint() == "" {
		t.Fatalf("an open wall needs wording: %+v", rotation)
	}
}

func TestLoadRotationMissing(t *testing.T) {
	t.Setenv("HOME", t.TempDir())
	rotation, ok := LoadRotation()
	if ok {
		t.Fatalf("a missing state file must not report a rotation: %+v", rotation)
	}
	if rotation.Known() {
		t.Fatal("a zero state must not be known")
	}
}

func TestLoadRotationRejectsGarbage(t *testing.T) {
	writeRotation(t, "{not json")
	if _, ok := LoadRotation(); ok {
		t.Fatal("an unreadable state file must be ignored")
	}
}

func TestRotationIdleHasNoSummary(t *testing.T) {
	rotation := Rotation{}
	if rotation.Summary() != "" || rotation.Hint() != "" {
		t.Fatal("an idle rotation has nothing to report")
	}
}

func formatUnix(moment time.Time) string {
	return strconv.FormatInt(moment.Unix(), 10)
}
