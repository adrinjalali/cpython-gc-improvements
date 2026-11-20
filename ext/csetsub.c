/* C subclasses of set/frozenset with their own tp_alloc.

   Before gh-152235, set_new/frozenset_new allocated through type->tp_alloc, as the
   C API documents.  Since then make_new_set() calls _PyType_AllocNoTrack() instead,
   so these types' allocator is no longer called, while their tp_free still is
   (patches/<branch>/tp-alloc fix that).

   Build and run: tools/run-ext.sh.  Use: csetsub.CSet(it), csetsub.CFrozen(it),
   csetsub.allocs() -> how many times the custom allocator ran.

   Also csetsub.set_new_borrowed(lst): PySet_New(lst[0]) on a *borrowed*
   reference, which the fill can drop (the generator clears lst), to check the
   gc-api patches hold their own reference to the iterator they track the set behind. */
#include <Python.h>

static Py_ssize_t allocs = 0;

static PyObject *
counting_alloc(PyTypeObject *type, Py_ssize_t nitems)
{
    allocs++;
    return PyType_GenericAlloc(type, nitems);
}

static PyTypeObject CSet_Type = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = "csetsub.CSet",
    .tp_basicsize = sizeof(PySetObject),
    .tp_flags = Py_TPFLAGS_DEFAULT | Py_TPFLAGS_BASETYPE,
    .tp_alloc = counting_alloc,
};

static PyTypeObject CFrozen_Type = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = "csetsub.CFrozen",
    .tp_basicsize = sizeof(PySetObject),
    .tp_flags = Py_TPFLAGS_DEFAULT | Py_TPFLAGS_BASETYPE,
    .tp_alloc = counting_alloc,
};

static PyObject *
get_allocs(PyObject *mod, PyObject *unused)
{
    return PyLong_FromSsize_t(allocs);
}

static PyObject *
set_new_borrowed(PyObject *mod, PyObject *lst)
{
    if (!PyList_Check(lst) || PyList_GET_SIZE(lst) != 1) {
        PyErr_SetString(PyExc_TypeError, "expected a 1-element list");
        return NULL;
    }
    return PySet_New(PyList_GET_ITEM(lst, 0));  /* borrowed */
}

static PyMethodDef methods[] = {
    {"allocs", get_allocs, METH_NOARGS, NULL},
    {"set_new_borrowed", set_new_borrowed, METH_O, NULL},
    {NULL},
};

static struct PyModuleDef module = {PyModuleDef_HEAD_INIT, "csetsub", NULL, -1, methods};

PyMODINIT_FUNC
PyInit_csetsub(void)
{
    CSet_Type.tp_base = &PySet_Type;
    CFrozen_Type.tp_base = &PyFrozenSet_Type;
    if (PyType_Ready(&CSet_Type) < 0 || PyType_Ready(&CFrozen_Type) < 0) {
        return NULL;
    }
    PyObject *m = PyModule_Create(&module);
    if (m == NULL) {
        return NULL;
    }
    if (PyModule_AddObjectRef(m, "CSet", (PyObject *)&CSet_Type) < 0 ||
        PyModule_AddObjectRef(m, "CFrozen", (PyObject *)&CFrozen_Type) < 0) {
        Py_DECREF(m);
        return NULL;
    }
    return m;
}
