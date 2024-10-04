package main
import "fmt"

func main() {
        var x [][]int
        i := 0
        for {
                i += 1
                if i%100000 == 0 {
                        fmt.Println("len", len(x))
                }
                x = append(x, make([]int, 1024*1024))

        }

}
