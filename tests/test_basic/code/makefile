all: code foo.o
code: main.c
	$(CXX) -o $@ $^
foo.o: foo.cpp foo.h
	$(CXX) -c foo.cpp
clean:
	rm -rf code
