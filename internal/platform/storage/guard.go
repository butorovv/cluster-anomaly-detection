package storage

import "fmt"

const MinimumFree = uint64(5 * 1024 * 1024 * 1024)

// Guard reserves 5 GiB plus the caller's anticipated output/cache growth.
func Guard(path string, reserve uint64) (uint64, error) {
	free, err := available(path)
	if err != nil {
		return 0, err
	}
	if free < MinimumFree || free-MinimumFree < reserve {
		return free, fmt.Errorf("disk guard: free=%d, required=%d", free, MinimumFree+reserve)
	}
	return free, nil
}
