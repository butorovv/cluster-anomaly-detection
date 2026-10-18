// Command score replays explicitly supplied D2 ticks through frozen models.
package main

import (
	"bufio"
	"bytes"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"math"
	"os"
	"reflect"
	"time"

	"cluster-anomaly-detection/internal/analysis"
	"cluster-anomaly-detection/internal/group"
	"cluster-anomaly-detection/internal/local"
	"cluster-anomaly-detection/internal/modules/telemetry/domain"
)

type inputRecord struct {
	Hostname string        `json:"hostname"`
	Features featureVector `json:"features"`
}

type featureVector []float64

func (f *featureVector) UnmarshalJSON(data []byte) error {
	var values []*float64
	if err := json.Unmarshal(data, &values); err != nil {
		return err
	}
	*f = make(featureVector, len(values))
	for i, v := range values {
		if v == nil {
			return fmt.Errorf("null feature is not a measured zero; omit the missing host record")
		}
		(*f)[i] = *v
	}
	return nil
}

type inputRow struct {
	ID        string        `json:"id"`
	Timestamp string        `json:"timestamp"`
	Group     string        `json:"group"`
	Records   []inputRecord `json:"records"`
}
type outputRow struct {
	ID  string    `json:"id"`
	Raw group.Raw `json:"raw"`
}

func validate(row inputRow, binding local.Binding) (time.Time, error) {
	if len(binding.Hosts) != 288 {
		return time.Time{}, fmt.Errorf("fixed 288-host binding required")
	}
	if row.ID == "" {
		return time.Time{}, fmt.Errorf("empty id")
	}
	if len(row.Group) != 3 || row.Group[0] != 'a' {
		return time.Time{}, fmt.Errorf("invalid group %q", row.Group)
	}
	var gi int
	if _, err := fmt.Sscanf(row.Group, "a%02d", &gi); err != nil || gi < 1 || gi > 16 || row.Group != fmt.Sprintf("a%02d", gi) {
		return time.Time{}, fmt.Errorf("invalid group %q", row.Group)
	}
	t, err := time.Parse(time.RFC3339, row.Timestamp)
	_, offset := t.Zone()
	if err != nil || offset != 0 {
		return time.Time{}, fmt.Errorf("timestamp must be RFC3339 UTC")
	}
	w := analysis.NIRWindows()[1]
	if !w.Contains(t) || t.Sub(w.Start)%analysis.Step != 0 {
		return time.Time{}, fmt.Errorf("timestamp outside D2 grid")
	}
	allowed := make(map[string]bool, group.HostsPerGroup)
	for _, host := range binding.Hosts[(gi-1)*group.HostsPerGroup : gi*group.HostsPerGroup] {
		allowed[host] = true
	}
	seen := map[string]bool{}
	for _, r := range row.Records {
		g, _, e := domain.ParseHostname(r.Hostname)
		if e != nil || g != row.Group || !allowed[r.Hostname] {
			return time.Time{}, fmt.Errorf("host %q does not belong to %s", r.Hostname, row.Group)
		}
		if seen[r.Hostname] {
			return time.Time{}, fmt.Errorf("duplicate host %q", r.Hostname)
		}
		seen[r.Hostname] = true
		if len(r.Features) != domain.FeatureCount {
			return time.Time{}, fmt.Errorf("%s requires exactly 18 features", r.Hostname)
		}
		for _, v := range r.Features {
			if math.IsNaN(v) || math.IsInf(v, 0) {
				return time.Time{}, fmt.Errorf("%s has nonfinite feature", r.Hostname)
			}
		}
	}
	return t, nil
}

func buildTick(row inputRow, binding local.Binding) (group.Tick, error) {
	t, err := validate(row, binding)
	if err != nil {
		return group.Tick{}, err
	}
	records := make(map[string]domain.TelemetryRecord, len(row.Records))
	for _, r := range row.Records {
		_, index, _ := domain.ParseHostname(r.Hostname)
		rec := domain.TelemetryRecord{Timestamp: t, Hostname: r.Hostname, GroupID: row.Group, NodeIndex: index, Valid: true, AvailabilityMask: domain.FullAvailabilityMask}
		var f [domain.FeatureCount]float64
		copy(f[:], r.Features)
		rec.SetFeatures(f)
		records[r.Hostname] = rec
	}
	return group.Tick{Timestamp: t, Records: records}, nil
}

func decodeLine(line []byte, row *inputRow) error {
	d := json.NewDecoder(bytes.NewReader(line))
	d.DisallowUnknownFields()
	if err := d.Decode(row); err != nil {
		return err
	}
	var extra any
	if err := d.Decode(&extra); err != io.EOF {
		if err == nil {
			return fmt.Errorf("trailing JSON value")
		}
		return err
	}
	return nil
}

func acceptID(ids map[string]bool, id string) error {
	if id == "" {
		return fmt.Errorf("empty id")
	}
	if ids[id] {
		return fmt.Errorf("duplicate id %q", id)
	}
	ids[id] = true
	return nil
}

func run() error {
	input := flag.String("input", "", "NDJSON input")
	output := flag.String("output", "", "new output file")
	prepared := flag.String("prepared", "data/prepared/summit-D1-pilot/D1.parquet", "immutable prepared D1")
	manifest := flag.String("manifest", "data/prepared/summit-D1-pilot/manifest.json", "prepared manifest")
	stat := flag.String("statistical-profile", "results/statistical-20220118-8h-v1.json", "frozen statistical profile")
	forest := flag.String("isolation-profile", "results/isolation-20220118-v1.json", "frozen IF")
	b1 := flag.String("b1-profile", "configs/local-b1.summit-20220118.json", "frozen local B1")
	hardware := flag.String("hardware", "configs/summit-hardware-reference.json", "approved hardware registry")
	gpPath := flag.String("group-profile", "configs/group-profile.summit-v1.json", "frozen group profile")
	flag.Parse()
	if *input == "" || *output == "" || flag.NArg() != 0 {
		return fmt.Errorf("--input NDJSON and --output NEW_FILE are required")
	}
	models, err := local.OpenModels(*prepared, *manifest, *stat, *forest)
	if err != nil {
		return err
	}
	lp, err := local.LoadProfile(*b1)
	if err != nil {
		return err
	}
	ld, err := local.NewDetector(lp, models.Forest, models.Binding)
	if err != nil {
		return err
	}
	gp, err := group.LoadProfile(*gpPath)
	if err != nil {
		return err
	}
	if !reflect.DeepEqual(gp.Binding, models.Binding) {
		return fmt.Errorf("group and local model bindings differ")
	}
	hw, err := group.LoadHardware(*hardware)
	if err != nil {
		return err
	}
	in, err := os.Open(*input)
	if err != nil {
		return err
	}
	defer in.Close()
	out, err := os.OpenFile(*output, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
	if err != nil {
		return err
	}
	defer out.Close()
	scan := bufio.NewScanner(in)
	scan.Buffer(make([]byte, 64*1024), 16*1024*1024)
	enc := json.NewEncoder(out)
	ids := map[string]bool{}
	for lineNo := 1; scan.Scan(); lineNo++ {
		var row inputRow
		if err = decodeLine(scan.Bytes(), &row); err != nil {
			return fmt.Errorf("line %d: %w", lineNo, err)
		}
		if e := acceptID(ids, row.ID); e != nil {
			return fmt.Errorf("line %d: %w", lineNo, e)
		}
		tick, e := buildTick(row, models.Binding)
		if e != nil {
			return fmt.Errorf("line %d: %w", lineNo, e)
		}
		var timing group.Timing
		raws, e := group.Evaluate(gp, tick, hw, ld, 16, &timing)
		if e != nil {
			return fmt.Errorf("line %d: %w", lineNo, e)
		}
		var selected *group.Raw
		for i := range raws {
			if raws[i].Group == row.Group {
				selected = &raws[i]
				break
			}
		}
		if selected == nil {
			return fmt.Errorf("line %d: requested group missing", lineNo)
		}
		if e = enc.Encode(outputRow{ID: row.ID, Raw: *selected}); e != nil {
			return e
		}
	}
	if err = scan.Err(); err != nil {
		return err
	}
	if err = out.Sync(); err != nil {
		return err
	}
	if err = out.Close(); err != nil && !errors.Is(err, os.ErrClosed) {
		return err
	}
	return nil
}

func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
