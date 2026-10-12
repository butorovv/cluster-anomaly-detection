package config

import (
	"flag"
	"fmt"
	"io"
	"math"
	"strconv"
)

type Config struct {
	DatabaseURL   string
	ReplayerInput string
	ReplayerSpeed float64
	LogLevel      string
	Output        string
}

// Load parses env and explicit flags. A valid flag overrides even a malformed env value.
func Load(args []string, getenv func(string) string, help io.Writer) (Config, error) {
	env := func(key, fallback string) string {
		if v := getenv(key); v != "" {
			return v
		}
		return fallback
	}
	cfg := Config{DatabaseURL: getenv("DATABASE_URL")}
	flags := flag.NewFlagSet("replayer", flag.ContinueOnError)
	flags.SetOutput(help)
	flags.StringVar(&cfg.ReplayerInput, "input", env("REPLAYER_INPUT", "data/prepared/D3.parquet"), "prepared D1/D2/D3 Parquet")
	speed := flags.String("speed", env("REPLAYER_SPEED", "1"), "pacing multiplier (0 = no intentional delay)")
	flags.StringVar(&cfg.LogLevel, "log-level", env("LOG_LEVEL", "INFO"), "DEBUG, INFO, WARN, ERROR")
	flags.StringVar(&cfg.Output, "output", "log", "log (summary; records at DEBUG) or stdout (NDJSON)")
	verbose := flags.Bool("verbose", false, "log individual records at DEBUG")
	if err := flags.Parse(args); err != nil {
		return cfg, err
	}
	if len(flags.Args()) != 0 {
		return cfg, fmt.Errorf("unexpected positional arguments")
	}
	var err error
	cfg.ReplayerSpeed, err = strconv.ParseFloat(*speed, 64)
	if err != nil || cfg.ReplayerSpeed < 0 || math.IsNaN(cfg.ReplayerSpeed) || math.IsInf(cfg.ReplayerSpeed, 0) {
		return cfg, fmt.Errorf("invalid replay speed: expected finite number >= 0")
	}
	if cfg.ReplayerInput == "" {
		return cfg, fmt.Errorf("replayer input is required")
	}
	if cfg.Output != "log" && cfg.Output != "stdout" {
		return cfg, fmt.Errorf("output must be log or stdout")
	}
	if *verbose {
		cfg.LogLevel = "DEBUG"
	}
	return cfg, nil
}
