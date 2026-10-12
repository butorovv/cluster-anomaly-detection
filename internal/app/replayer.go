package app

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"os/signal"
	"syscall"

	"cluster-anomaly-detection/internal/platform/config"
	"cluster-anomaly-detection/internal/platform/logger"
	"cluster-anomaly-detection/internal/replayer"
)

func RunReplayer() int {
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	if err := Replayer(ctx, os.Args[1:], os.Getenv, os.Stdout, os.Stderr); err != nil {
		if errors.Is(err, flag.ErrHelp) {
			return 0
		}
		if errors.Is(err, context.Canceled) {
			return 130
		}
		fmt.Fprintln(os.Stderr, "replayer failed:", err)
		return 1
	}
	return 0
}

func Replayer(ctx context.Context, args []string, getenv func(string) string, stdout, stderr io.Writer) (result error) {
	cfg, err := config.Load(args, getenv, stderr)
	if err != nil {
		return err
	}
	log, err := logger.New(cfg.LogLevel, stderr)
	if err != nil {
		return fmt.Errorf("log level: %w", err)
	}
	reader, err := replayer.OpenParquet(cfg.ReplayerInput)
	if err != nil {
		return err
	}
	defer func() { result = errors.Join(result, reader.Close()) }()
	log.InfoContext(ctx, "dataset loaded", "input", cfg.ReplayerInput, "rows", reader.Rows())
	var sender replayer.TelemetrySender
	var complete replayer.TimestampCompleter
	if cfg.Output == "stdout" {
		output := replayer.NewJSONSender(stdout)
		sender, complete = output, output
	} else {
		output := replayer.LogSender{Logger: log}
		sender, complete = output, output
	}
	log.InfoContext(ctx, "replay started", "speed", cfg.ReplayerSpeed)
	stats, err := replayer.Replay(ctx, reader, sender, complete, replayer.RealClock{}, cfg.ReplayerSpeed)
	if err != nil {
		log.ErrorContext(ctx, "replay failed", "error", err, "rows_sent", stats.Rows)
		return err
	}
	log.InfoContext(ctx, "replay finished", "rows", stats.Rows, "timestamps", stats.Timestamps, "groups", stats.Groups, "hosts", stats.Hosts, "invalid", stats.Invalid, "timestamp_completions", stats.Completions)
	return nil
}
