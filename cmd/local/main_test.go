package main

import (
	"bytes"
	"context"
	"strings"
	"testing"
)

func TestRejectInvalidFlagCombinationsBeforeReadingModels(t *testing.T) {
	for _, tc := range []struct {
		args    []string
		message string
	}{
		{[]string{"--window", "D4"}, "--window"},
		{[]string{"--import-context", "export"}, "requires --build-profile"},
		{[]string{"--build-profile", "new.json", "--summary-only"}, "cannot be combined"},
		{[]string{"extra"}, "unexpected positional"},
	} {
		var stdout, stderr bytes.Buffer
		err := run(context.Background(), tc.args, &stdout, &stderr)
		if err == nil || !strings.Contains(err.Error(), tc.message) || stdout.Len() != 0 {
			t.Fatal(tc, err, stdout.String())
		}
	}
}
