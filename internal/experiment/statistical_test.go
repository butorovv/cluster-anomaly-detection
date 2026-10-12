package experiment

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

func TestSaveNewPreservesExistingResults(t *testing.T) {
	path := filepath.Join(t.TempDir(), "profile.json")
	if err := SaveNew(path, map[string]int{"rank": 18}); err != nil {
		t.Fatal(err)
	}
	if err := SaveNew(path, map[string]int{"rank": 0}); err == nil {
		t.Fatal("overwrote existing result")
	}
	b, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var m map[string]int
	if err = json.Unmarshal(b, &m); err != nil || m["rank"] != 18 {
		t.Fatal(string(b), err)
	}
}
