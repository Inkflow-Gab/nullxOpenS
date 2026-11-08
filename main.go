// Command nullx is a terminal coding agent backed by an
// OpenAI-compatible gateway.
package main

import (
	"fmt"
	"os"

	"github.com/Inkflow-Gab/nullxOpenS/internal/cmd"
)

func main() {
	if err := cmd.Run(os.Args[1:]); err != nil {
		fmt.Fprintln(os.Stderr, "nullx:", err)
		os.Exit(1)
	}
}
