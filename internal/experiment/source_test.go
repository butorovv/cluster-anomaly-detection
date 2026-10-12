package experiment

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"testing"

	"cluster-anomaly-detection/internal/modules/telemetry/domain"
)

func TestSourceManifestIdentityChecksumAndFeatureOrder(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "synthetic-input.bin")
	manifest := filepath.Join(dir, "manifest.json")
	content := []byte("only checksum validation; not a Parquet fixture")
	if err := os.WriteFile(path, content, 0600); err != nil {
		t.Fatal(err)
	}
	hash := sha256.Sum256(content)
	makeManifest := func() map[string]any {
		hosts := []string{}
		groups := []string{}
		for g := 1; g <= 16; g++ {
			groups = append(groups, fmt.Sprintf("a%02d", g))
			for n := 1; n <= 18; n++ {
				hosts = append(hosts, fmt.Sprintf("a%02dn%02d", g, n))
			}
		}
		return map[string]any{"feature_order": append([]string(nil), domain.FeatureNames[:]...), "schema_version": "F18-v1", "selected_hosts": hosts, "selected_groups": groups, "prepared_file_hashes": map[string]string{filepath.Base(path): hex.EncodeToString(hash[:])}, "assumed_timezone": "UTC", "timezone_verified": false}
	}
	check := func(m map[string]any, wantErr bool) {
		t.Helper()
		b, err := json.Marshal(m)
		if err != nil {
			t.Fatal(err)
		}
		if err = os.WriteFile(manifest, b, 0600); err != nil {
			t.Fatal(err)
		}
		_, err = OpenSource(path, manifest)
		if (err != nil) != wantErr {
			t.Fatalf("error=%v expected error=%t", err, wantErr)
		}
	}
	check(makeManifest(), false)
	m := makeManifest()
	m["feature_order"] = append(m["feature_order"].([]string), "extra")
	check(m, true)
	m = makeManifest()
	f := m["feature_order"].([]string)
	f[0], f[1] = f[1], f[0]
	check(m, true)
	m = makeManifest()
	hosts := m["selected_hosts"].([]string)
	hosts[1] = hosts[0]
	check(m, true)
	m = makeManifest()
	groups := m["selected_groups"].([]string)
	groups[1] = groups[0]
	check(m, true)
	m = makeManifest()
	m["prepared_file_hashes"] = map[string]string{filepath.Base(path): "wrong"}
	check(m, true)
}
