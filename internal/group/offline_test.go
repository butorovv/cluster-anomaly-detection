package group

import "testing"

func TestAnnotateOutsideUsesAvailableHostWeights(t *testing.T) {
	rows := []Raw{
		{Group: "a", IF: Support{Available: 1, Anomalous: 1, S: ptr(1)}},
		{Group: "b", IF: Support{Available: 9, Anomalous: 0, S: ptr(0)}},
		{Group: "c", IF: Support{Available: 0, Anomalous: 0}},
	}
	AnnotateOutside(rows)
	if rows[0].IF.OutsideAvailable != 9 || rows[0].IF.OutsideAnomalous != 0 || rows[0].IF.OutsideS == nil || *rows[0].IF.OutsideS != 0 || rows[0].IF.E == nil || *rows[0].IF.E != 1 {
		t.Fatalf("weighted outside annotation: %+v", rows[0].IF)
	}
	if rows[2].IF.OutsideAvailable != 10 || rows[2].IF.OutsideS == nil || *rows[2].IF.OutsideS != 0.1 || rows[2].IF.E != nil {
		t.Fatalf("outside score/unknown own score: %+v", rows[2].IF)
	}
	zero := []Raw{{Group: "a", IF: Support{Available: 0}}, {Group: "b", IF: Support{Available: 0}}}
	AnnotateOutside(zero)
	if zero[0].IF.OutsideS != nil || zero[0].IF.E != nil {
		t.Fatal("zero denominator must remain unknown")
	}
}
