package storage

import (
	"path/filepath"

	"golang.org/x/sys/windows"
)

func available(path string) (uint64, error) {
	abs, err := filepath.Abs(path)
	if err != nil {
		return 0, err
	}
	p, err := windows.UTF16PtrFromString(filepath.VolumeName(abs) + `\`)
	if err != nil {
		return 0, err
	}
	var free, total, all uint64
	err = windows.GetDiskFreeSpaceEx(p, &free, &total, &all)
	return free, err
}
