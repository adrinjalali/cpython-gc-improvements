import gc, sys
import csetsub

for cls, name in ((csetsub.CSet, "CSet"), (csetsub.CFrozen, "CFrozen")):
    before = csetsub.allocs()
    objs = [cls(x for x in range(10)) for _ in range(100)]
    ran = csetsub.allocs() - before
    tracked = all(gc.is_tracked(o) for o in objs)
    ok = ran == 100 and tracked and all(len(o) == 10 for o in objs)
    print(f"{'OK    ' if ok else 'BROKEN'} {name}(gen) x100: custom tp_alloc ran {ran} times, all tracked={tracked}")

# PySet_New() on a borrowed generator whose only owner (lst) is cleared mid-fill.
class Val:
    def __init__(self, v): self.v = v
    def __hash__(self): return hash(self.v)
    def __eq__(self, o): return self.v == o.v

ok = True
for _ in range(200):
    lst = []
    def gen():
        lst.clear()  # drops the only reference the caller had
        yield from (Val(i) for i in range(20))
    lst.append(gen())
    s = csetsub.set_new_borrowed(lst)
    ok = ok and len(s) == 20 and gc.is_tracked(s)
gc.collect()
print(f"{'OK    ' if ok else 'BROKEN'} PySet_New(borrowed generator dropped mid-fill) x200")
