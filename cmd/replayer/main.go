package main

import (
	"cluster-anomaly-detection/internal/app"
	"os"
)

func main() { os.Exit(app.RunReplayer()) }
