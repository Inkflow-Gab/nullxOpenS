// Package session persists conversations as JSON files.
package session

import (
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"time"

	"github.com/Inkflow-Gab/nullxOpenS/internal/llm"
)

// Session is one saved conversation.
type Session struct {
	ID       string        `json:"id"`
	Created  time.Time     `json:"created"`
	Messages []llm.Message `json:"messages"`

	path string
}

// Meta is the summary shown by the sessions command.
type Meta struct {
	ID       string    `json:"id"`
	Created  time.Time `json:"created"`
	Messages int       `json:"messages"`
}

// New creates and saves a fresh session in dir.
func New(dir string) (*Session, error) {
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return nil, err
	}
	id, err := newID()
	if err != nil {
		return nil, err
	}
	session := &Session{
		ID:      id,
		Created: time.Now().UTC(),
		path:    filepath.Join(dir, id+".json"),
	}
	if err := session.Save(); err != nil {
		return nil, err
	}
	return session, nil
}

// Load reads a session by ID from dir.
func Load(dir, id string) (*Session, error) {
	path := filepath.Join(dir, id+".json")
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	var session Session
	if err := json.Unmarshal(data, &session); err != nil {
		return nil, err
	}
	session.path = path
	return &session, nil
}

// List returns the sessions in dir, newest first.
func List(dir string) ([]Meta, error) {
	entries, err := os.ReadDir(dir)
	if err != nil {
		if os.IsNotExist(err) {
			return nil, nil
		}
		return nil, err
	}
	metas := make([]Meta, 0, len(entries))
	for _, entry := range entries {
		if entry.IsDir() || filepath.Ext(entry.Name()) != ".json" {
			continue
		}
		data, err := os.ReadFile(filepath.Join(dir, entry.Name()))
		if err != nil {
			continue
		}
		var session Session
		if err := json.Unmarshal(data, &session); err != nil {
			continue
		}
		metas = append(metas, Meta{ID: session.ID, Created: session.Created, Messages: len(session.Messages)})
	}
	sort.Slice(metas, func(i, j int) bool {
		return metas[i].Created.After(metas[j].Created)
	})
	return metas, nil
}

// Save writes the session atomically.
func (s *Session) Save() error {
	if s.path == "" {
		return nil
	}
	data, err := json.MarshalIndent(s, "", "  ")
	if err != nil {
		return err
	}
	temp := s.path + ".tmp"
	if err := os.WriteFile(temp, data, 0o600); err != nil {
		return err
	}
	return os.Rename(temp, s.path)
}

func newID() (string, error) {
	buffer := make([]byte, 4)
	if _, err := rand.Read(buffer); err != nil {
		return "", err
	}
	return fmt.Sprintf("%s-%s", time.Now().Format("20060102-150405"), hex.EncodeToString(buffer)), nil
}
