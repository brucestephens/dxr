template <class T>
struct Foo {
  T a;
  bool operator==(const Foo<T>& other) const;
  operator bool() const {
    return true;
  }
};

typedef Foo<int> FooInt;

template <class T>
T foo(const T&);
