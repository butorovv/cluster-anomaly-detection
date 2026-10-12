package config

import (
	"io"
	"testing"
)

func TestExplicitFlagsOverrideEnvironment(t *testing.T) {
	env := map[string]string{"REPLAYER_INPUT": "old.parquet", "REPLAYER_SPEED": "broken", "LOG_LEVEL": "ERROR", "DATABASE_URL": "local"}
	get := func(key string) string { return env[key] }
	cfg, err := Load([]string{"--input", "new.parquet", "--speed", "100", "--verbose"}, get, io.Discard)
	if err != nil {
		t.Fatal(err)
	}
	if cfg.ReplayerInput != "new.parquet" || cfg.ReplayerSpeed != 100 || cfg.LogLevel != "DEBUG" || cfg.DatabaseURL != "local" {
		t.Fatal(cfg)
	}
	if _, err := Load(nil, get, io.Discard); err == nil {
		t.Fatal("invalid environment speed accepted")
	}
	for _, speed := range []string{"NaN", "Inf", "-1", "garbage"} {
		if _, err := Load([]string{"--speed", speed}, get, io.Discard); err == nil {
			t.Fatal("bad speed accepted")
		}
	}
}
