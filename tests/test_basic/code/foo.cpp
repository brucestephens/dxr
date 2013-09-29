#include "foo.h"

template<>
bool FooInt::operator==(const FooInt&other) const
{
  return a == other.a;
}

template<>
int foo(const int& a)
{
  return a+1;
}

void
test()
{
  FooInt f, g;
  bool eq = f == g;

  int b = foo(7);
  bool a = f;
}
