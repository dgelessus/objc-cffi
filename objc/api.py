import builtins
import collections
import collections.abc
import ctypes
import importlib
import sys
import threading
import traceback
import weakref

import cffi
import cffi.backend_ctypes
import objc_util

from . import data
from . import encoding

__all__ = [
	"Block",
	"BoundMethod",
	"Class",
	"ID",
	"Ivar",
	"LP64",
	"MetaClass",
	"Method",
	"Property",
	"Protocol",
	"Selector",
	"coerce",
	"ffi",
	"format_address",
	"free",
	"gc_free",
	"libc",
	"to_array",
	"to_data",
	"to_dictionary",
	"to_set",
	"to_string",
	"unwrap_cdata",
]

SHORT_PROPERTIES = False

# Install the loaders for objc.classes and objc.protocols (can only be used once Class and Protocol has been defined, respectively).

class _ClassModuleProxy(type(sys)):
	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self._known_names = set()
	
	def __dir__(self):
		return {*super().__dir__(), *self._known_names}
	
	def __getattr__(self, name):
		try:
			cls = Class(name)
		except ValueError as err:
			self._known_names.discard(name)
			raise AttributeError(*err.args)
		else:
			self._known_names.add(name)
			return cls

class _ProtocolModuleProxy(type(sys)):
	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self._known_names = set()
	
	def __dir__(self):
		return {*super().__dir__(), *self._known_names}
	
	def __getattr__(self, name):
		try:
			proto = Protocol(name)
		except ValueError as err:
			self._known_names.discard(name)
			raise AttributeError(*err.args)
		else:
			self._known_names.add(name)
			return proto

_MODULE_PROXIES = {
	"objc.classes": _ClassModuleProxy,
	"objc.protocols": _ProtocolModuleProxy,
}

class _ObjcSpecialFinderLoader(object):
	def find_module(self, fullname, path=None):
		return self if fullname in _MODULE_PROXIES else None
	
	def load_module(self, fullname):
		mod = sys.modules.setdefault(fullname, _MODULE_PROXIES[fullname](fullname))
		mod.__file__ = "<dynamically created by {cls.__module__}.{cls.__qualname__}>".format(cls=type(self))
		mod.__loader__ = self
		mod.__package__ = "objc"
		mod.__all__ = ["DontEvenTryToStarImportThisModuleYouCrazyPerson"]
		return mod

# Remove old versions of the loader and modules if the objc module is reloaded.

for obj in sys.meta_path:
	if type(obj).__module__ == "objc.api" and type(obj).__name__ == "_ObjcSpecialFinderLoader":
		sys.meta_path.remove(obj)
		break
del obj

sys.meta_path.append(_ObjcSpecialFinderLoader())
sys.modules.pop("objc.classes", None)
sys.modules.pop("objc.protocols", None)
from . import classes
from . import protocols

##__all__ = [] # TODO

LP64 = sys.maxsize > 2**31 - 1

ffi = cffi.FFI(backend=cffi.backend_ctypes.CTypesBackend())
libc = ffi.dlopen(None)

ffi.cdef("""
// Lots of standard C definitions.
// Also redefine all the standard integer types.
// Most of them are defined by CFFI automatically, but that can't always be trusted with the ctypes backend.
// The boolean types _Bool and bool are defined okay, so we leave those alone.

// stdarg.h

typedef void *__builtin_va_list;
typedef __builtin_va_list va_list;

// stddef.h

typedef long ssize_t;
typedef unsigned long size_t;
typedef long ptrdiff_t;

typedef int wchar_t;

// stdint.h

typedef signed char int8_t;
typedef unsigned char uint8_t;
typedef short int16_t;
typedef unsigned short uint16_t;
typedef int int32_t;
typedef unsigned int uint32_t;
typedef long long int64_t;
typedef unsigned long long uint64_t;

typedef int8_t int_least8_t;
typedef uint8_t uint_least8_t;
typedef int16_t int_least16_t;
typedef uint16_t uint_least16_t;
typedef int32_t int_least32_t;
typedef uint32_t uint_least32_t;
typedef int64_t int_least64_t;
typedef uint64_t uint_least64_t;

typedef int8_t int_fast8_t;
typedef uint8_t uint_fast8_t;
typedef int16_t int_fast16_t;
typedef uint16_t uint_fast16_t;
typedef int32_t int_fast32_t;
typedef uint32_t uint_fast32_t;
typedef int64_t int_fast64_t;
typedef uint64_t uint_fast64_t;

typedef int64_t intmax_t;
typedef uint64_t uintmax_t;

typedef long intptr_t;
typedef unsigned long uintptr_t;

// stdlib.h

void free(void *ptr);

// wctype.h

typedef int wint_t;

// A few struct/union types that should never be completed.

// Placeholder for an unknown type.
typedef struct DGUnknownType unknown_type;

// Placeholders for a struct and union of unknown name.
typedef struct DGUnknownStruct unknown_struct;
typedef union DGUnknownUnion unknown_union;

// Placeholders for the return type and argument list of a polymorphic function that has not been cast to a concrete signature.
typedef struct DGUncastPolymorphicReturn uncast_polymorphic_return;
typedef struct DGUncastPolymorphicArguments uncast_polymorphic_arguments;
""")

ffi.cdef("typedef bool BOOL;" if LP64 else "typedef signed char BOOL;")

ffi.cdef("""

// Types

typedef struct objc_object *id;
typedef struct objc_class *Class;
typedef struct objc_category *Category;
typedef struct objc_ivar *Ivar;
typedef struct objc_method *Method;
typedef struct objc_property *objc_property_t;
typedef struct objc_selector *SEL;

// Nicer names for the structs (used in the repr of pointer cdata)
typedef struct objc_object id_s;
typedef struct objc_class Class_s;
typedef struct objc_category Category_s;
typedef struct objc_ivar Ivar_s;
typedef struct objc_method Method_s;
typedef struct objc_property objc_property_t_s;
typedef struct objc_selector SEL_s;

// This is part of objc/runtime.h, but has to come after the "nice name" typedefs so they take priority.
// Otherwise every id is displayed as a Protocol * by cffi.
typedef struct objc_object Protocol; // Protocol is actually a class

// Blocks

typedef id_s NSBlock;

enum {
	BLOCK_HAS_COPY_DISPOSE = 0x2000000, // 1 << 25
	BLOCK_HAS_CTOR = 0x4000000, // 1 << 26
	BLOCK_IS_GLOBAL = 0x10000000, // 1 << 28
	BLOCK_HAS_STRET = 0x20000000, // 1 << 29 // Should be ignored if not flags & BLOCK_HAS_SIGNATURE
	BLOCK_HAS_SIGNATURE = 0x40000000, // 1 << 30
};

struct Block_literal {
	Class isa;
	int flags; // see the above enum
	int reserved;
	uncast_polymorphic_return (*invoke)(id self, uncast_polymorphic_arguments args);
	struct Block_descriptor {
		unsigned long reserved;
		unsigned long size; // sizeof(struct Block_literal_1)
		//void (*copy_helper)(id dst, id src); // optional, only if flags & BLOCK_HAS_COPY_DISPOSE
		//void (*dispose_helper)(id src); // optional, only if flags & BLOCK_HAS_COPY_DISPOSE
		//const char *signature; // only present if flags & BLOCK_HAS_SIGNATURE, but required by blocks ABI.2010.3.16
	} *descriptor;
};

// Misc typedefs from objc/objc.h, objc/runtime.h and objc/message.h

typedef uncast_polymorphic_return (*IMP)(id self, SEL _cmd, uncast_polymorphic_arguments args);

struct objc_method_description {
	SEL name;
	char *types;
};

typedef struct {
	const char *name;
	const char *value;
} objc_property_attribute_t;

typedef enum {
	OBJC_ASSOCIATION_ASSIGN = 0,
	OBJC_ASSOCIATION_RETAIN_NONATOMIC = 1,
	OBJC_ASSOCIATION_COPY_NONATOMIC = 3,
	OBJC_ASSOCIATION_RETAIN = 01401,
	OBJC_ASSOCIATION_COPY = 01403
} objc_AssociationPolicy;

struct objc_super {
	id receiver;
	Class super_class;
};

// General functions

//extern uncast_polymorphic_return _objc_msgForward(id receiver, SEL sel, uncast_polymorphic_arguments args);
extern Class objc_allocateClassPair(Class superclass, const char *name, size_t extraBytes);
extern Protocol *objc_allocateProtocol(const char *name);
//extern id objc_constructInstance(Class cls, void *bytes);
extern Class *objc_copyClassList(unsigned int *outCount);
extern const char **objc_copyClassNamesForImage(const char *image, unsigned int *outCount);
extern const char **objc_copyImageNames(unsigned int *outCount);
extern Protocol **objc_copyProtocolList(unsigned int *outCount);
//extern void *objc_destructInstance(id obj);
//extern void objc_disposeClassPair(Class cls);
//extern void objc_enumerationMutation(id obj);
extern id objc_getAssociatedObject(id object, const void *key);
extern Class objc_getClass(const char *name);
extern int objc_getClassList(Class *buffer, int bufferCount);
extern Class objc_getMetaClass(const char *name);
extern Protocol *objc_getProtocol(const char *name);
//extern Class objc_getRequiredClass(const char *name);
extern id objc_loadWeak(id *location);
//extern Class objc_lookUpClass(const char *name);
extern uncast_polymorphic_return objc_msgSend(id self, SEL op, uncast_polymorphic_arguments args);
extern uncast_polymorphic_return objc_msgSendSuper(struct objc_super *super, SEL op, uncast_polymorphic_arguments args);
extern void objc_registerClassPair(Class cls);
extern void objc_registerProtocol(Protocol *proto);
extern void objc_removeAssociatedObjects(id object);
extern void objc_setAssociatedObject(id object, const void *key, id value, objc_AssociationPolicy policy);
//extern void objc_setEnumerationMutationHandler(void (*handler)(id));
//extern void objc_setForwardHandler(void *fwd, void *fwd_stret);
extern id objc_storeWeak(id *location, id obj);

// Classes

extern BOOL class_addIvar(Class cls, const char *name, size_t size, uint8_t alignment, const char *types);
extern BOOL class_addMethod(Class cls, SEL name, IMP imp, const char *types);
extern BOOL class_addProperty(Class cls, const char *name, const objc_property_attribute_t *attributes, unsigned int attributeCount);
extern BOOL class_addProtocol(Class cls, Protocol *protocol);
extern BOOL class_conformsToProtocol(Class cls, Protocol *protocol);
extern Ivar *class_copyIvarList(Class cls, unsigned int *outCount);
extern Method *class_copyMethodList(Class cls, unsigned int *outCount);
extern objc_property_t *class_copyPropertyList(Class cls, unsigned int *outCount);
extern Protocol **class_copyProtocolList(Class cls, unsigned int *outCount);
//extern id class_createInstance(Class cls, size_t extraBytes);
extern Method class_getClassMethod(Class cls, SEL name);
extern Ivar class_getClassVariable(Class cls, const char *name);
extern const char *class_getImageName(Class cls);
extern Method class_getInstanceMethod(Class cls, SEL name);
extern size_t class_getInstanceSize(Class cls);
extern Ivar class_getInstanceVariable(Class cls, const char *name);
extern const uint8_t *class_getIvarLayout(Class cls);
extern IMP class_getMethodImplementation(Class cls, SEL name);
extern const char *class_getName(Class cls);
extern objc_property_t class_getProperty(Class cls, const char *name);
extern Class class_getSuperclass(Class cls);
extern int class_getVersion(Class cls);
extern const uint8_t *class_getWeakIvarLayout(Class cls);
extern BOOL class_isMetaClass(Class cls);
extern IMP class_replaceMethod(Class cls, SEL name, IMP imp, const char *types);
extern void class_replaceProperty(Class cls, const char *name, const objc_property_attribute_t *attributes, unsigned int attributeCount);
extern BOOL class_respondsToSelector(Class cls, SEL sel);
extern void class_setIvarLayout(Class cls, const uint8_t *layout);
extern void class_setVersion(Class cls, int version);
extern void class_setWeakIvarLayout(Class cls, const uint8_t *layout);

// Objects

//extern id object_copy(id obj, size_t size);
//extern id object_dispose(id obj);
extern Class object_getClass(id obj);
extern const char *object_getClassName(id obj);
extern void *object_getIndexedIvars(id obj);
extern Ivar object_getInstanceVariable(id obj, const char *name, void **outValue);
extern id object_getIvar(id obj, Ivar ivar);
extern BOOL object_isClass(id obj);
extern Class object_setClass(id obj, Class cls);
extern Ivar object_setInstanceVariable(id obj, const char *name, void *value);
extern void object_setIvar(id obj, Ivar ivar, id value);

// Selectors

extern const char *sel_getName(SEL sel);
//extern BOOL sel_isEqual(SEL lhs, SEL rhs);
extern BOOL sel_isMapped(SEL sel);
extern SEL sel_registerName(const char *str);

// Methods

extern char *method_copyArgumentType(Method m, unsigned int index);
extern char *method_copyReturnType(Method m);
extern void method_exchangeImplementations(Method m1, Method m2);
extern void method_getArgumentType(Method m, unsigned int index, char *dst, size_t dst_len);
extern struct objc_method_description *method_getDescription(Method m);
extern IMP method_getImplementation(Method m);
extern SEL method_getName(Method m);
extern unsigned int method_getNumberOfArguments(Method m);
extern void method_getReturnType(Method m, char *dst, size_t dst_len);
extern const char *method_getTypeEncoding(Method m);
extern uncast_polymorphic_return method_invoke(id receiver, Method m, uncast_polymorphic_arguments args);
extern IMP method_setImplementation(Method m, IMP imp);

// Implementations

extern id imp_getBlock(IMP anImp);
extern IMP imp_implementationWithBlock(id block);
extern BOOL imp_removeBlock(IMP anImp);

// Ivars

extern const char *ivar_getName(Ivar v);
extern ptrdiff_t ivar_getOffset(Ivar v);
extern const char *ivar_getTypeEncoding(Ivar v);

// Properties

extern objc_property_attribute_t *property_copyAttributeList(objc_property_t property, unsigned int *outCount);
extern char *property_copyAttributeValue(objc_property_t property, const char *attributeName);
extern const char *property_getAttributes(objc_property_t property);
extern const char *property_getName(objc_property_t property);

// Protocols

extern void protocol_addMethodDescription(Protocol *proto, SEL name, const char *types, BOOL isRequiredMethod, BOOL isInstanceMethod);
extern void protocol_addProperty(Protocol *proto, const char *name, const objc_property_attribute_t *attributes, unsigned int attributeCount, BOOL isRequiredProperty, BOOL isInstanceProperty);
extern void protocol_addProtocol(Protocol *proto, Protocol *addition);
extern BOOL protocol_conformsToProtocol(Protocol *proto, Protocol *other);
extern struct objc_method_description *protocol_copyMethodDescriptionList(Protocol *p, BOOL isRequiredMethod, BOOL isInstanceMethod, unsigned int *outCount);
extern objc_property_t *protocol_copyPropertyList(Protocol *proto, unsigned int *outCount);
extern Protocol **protocol_copyProtocolList(Protocol *proto, unsigned int *outCount);
extern struct objc_method_description protocol_getMethodDescription(Protocol *p, SEL aSel, BOOL isRequiredMethod, BOOL isInstanceMethod);
extern const char *protocol_getName(Protocol *p);
extern objc_property_t protocol_getProperty(Protocol *proto, const char *name, BOOL isRequiredProperty, BOOL isInstanceProperty);
extern BOOL protocol_isEqual(Protocol *proto, Protocol *other);
""")

if not LP64:
	# On 32-bit ARM, we need to use the stret versions of these functions when the return type is something other than an integer (including booleans and enums) or a floating-point number.
	ffi.cdef("""
	extern IMP class_getMethodImplementation_stret(Class cls, SEL name);
	
	extern uncast_polymorphic_return _objc_msgForward_stret(id receiver, SEL sel, uncast_polymorphic_arguments args);
	extern uncast_polymorphic_return objc_msgSend_stret(id self, SEL op, uncast_polymorphic_arguments args);
	extern uncast_polymorphic_return objc_msgSendSuper_stret(struct objc_super *super, SEL op, uncast_polymorphic_arguments args);
	extern uncast_polymorphic_return method_invoke_stret(id receiver, Method m, uncast_polymorphic_arguments args);
	""")

void = ffi.typeof("void")
INTEGER_TYPES = (
	ffi.typeof("signed char"),
	ffi.typeof("unsigned char"),
	ffi.typeof("short"),
	ffi.typeof("unsigned short"),
	ffi.typeof("int"),
	ffi.typeof("unsigned int"),
	ffi.typeof("long"),
	ffi.typeof("unsigned long"),
	ffi.typeof("long long"),
	ffi.typeof("unsigned long long"),
)

def free(ptr):
	"""Free the given pointer, as returned by C malloc. If it is NULL, nothing happens."""
	
	libc.free(ptr)

def gc_free(ptr):
	"""Return a copy of the given pointer which automatically frees itself (and the original) when the copy is garbage-collected."""
	
	return ffi.gc(ptr, free)
	
def _retain(ptr):
	"""Send a retain message to the given id cdata.
	
	Do not call directly, ID retains and releases objects automatically."""
	
	_objc_msgSend_retain(ptr, libc.sel_registerName(b"retain"))

def _release(ptr):
	"""Send a release message to the given id cdata. The object cannot be used anymore afterwards.
	
	Do not call directly, ID retains and releases objects automatically."""
	
	_objc_msgSend_release(ptr, libc.sel_registerName(b"release"))

def _gc_release(ptr):
	"""Return a copy of the given pointer which automatically releases itself (and the original) when the copy is garbage-collected.
	
	Do not call directly, ID retains and releases objects automatically.
	"""
	
	return ffi.gc(ptr, _release)

def format_address(addr):
	"""Format the given address (an integer or a cdata castable to uintptr_t) in hex representation as a string. The representation is 16 hex digits long in a 64-bit environment, and 8 hex digits long otherwise."""
	
	try:
		ffi.typeof(addr)
	except TypeError:
		pass
	else:
		addr = int(ffi.cast("uintptr_t", addr))
	
	return "0x{addr:0{width}x}".format(addr=addr, width=16 if LP64 else 8)

def _encoding_type_to_cffi(tp):
	"""Convert the given type object from objc.encoding into a CFFI type."""
	
	if not isinstance(tp, encoding.BaseType):
		raise TypeError("tp must be an instance of a objc.encoding.BaseType subclass")
	
	if isinstance(tp, encoding.InternalType):
		raise TypeError("Internal types (e. g. fields and bit fields) cannot be converted to CFFI types directly")
	
	if isinstance(tp, encoding.QualifiedType):
		return _encoding_type_to_cffi(tp.type)
	elif isinstance(tp, encoding.UnknownType):
		return ffi.typeof("unknown_type")
	elif isinstance(tp, encoding.Void):
		return ffi.typeof("void")
	elif isinstance(tp, encoding.Scalar):
		return ffi.typeof(tp.type)
	elif isinstance(tp, encoding.Pointer):
		return ffi.typeof(ffi.getctype(_encoding_type_to_cffi(tp.element_type), "*"))
	elif isinstance(tp, encoding.ID):
		return ffi.typeof("id")
	elif isinstance(tp, encoding.Class):
		return ffi.typeof("Class")
	elif isinstance(tp, encoding.Selector):
		return ffi.typeof("SEL")
	elif isinstance(tp, encoding.Array):
		return ffi.typeof(ffi.getctype(_encoding_type_to_cffi(tp.element_type), "[{}]".format(tp.length)))
	elif isinstance(tp, (encoding.Struct, encoding.Union)):
		kw = "struct" if isinstance(tp, encoding.Struct) else "union"
		
		if tp.name is None and tp.fields is None:
			return ffi.typeof("unknown_{}".format(kw))
		
		name = "" if tp.name is None else tp.name
		
		if tp.fields is None:
			decl = "{kw} {name}".format(kw=kw, name=name)
		else:
			fields = []
			for i, field in enumerate(tp.fields):
				field_name = "_field_{}".format(i) if field.name is None else field.name
				if isinstance(field.type, encoding.BitField):
					if field.type.width == 1:
						field_decl = "bool {} : 1;".format(field_name)
					else:
						field_decl = "unsigned int {} : {};".format(field_name, field.type.width)
				else:
					field_decl = ffi.getctype(_encoding_type_to_cffi(field.type), field_name) + ";"
				fields.append(field_decl)
			
			if not fields:
				fields.append("char _empty[0];")
			
			decl = "{kw} {name} {{{fields}}}".format(kw=kw, name=name, fields="".join(fields))
		
		return ffi.typeof(decl)

def _must_use_stret(restype):
	"""Return whether the stret version of a polymorphic function (such as objc_msgSend) must be used for the given return type.
	
	Return True when on 32-bit ARM and the return type is a direct struct (not a struct pointer), otherwise False.
	No idea how unions need to be handled, to be honest. Right now, we don't, and hope that the normal non-stret function works. It should work as long as the union is made up of only scalars.
	"""
	
	return not LP64 and restype != void and restype.kind == "struct"

def _make_function_ptr_ctype(restype, argtypes):
	"""Return a function pointer ctype for the given return type and argument types.
	
	This ctype can for example be used to cast an existing function to a different signature.
	"""
	
	if restype != void:
		try:
			restype.kind
		except AttributeError:
			raise TypeError("restype ({}) has no kind attribute. This usually means that restype is an array type, which is not a valid return type.".format(restype))
	
	argdecls = []
	for i, argtype in enumerate(argtypes):
		if argtype is ...:
			if i != len(argtypes) - 1:
				raise ValueError("... can only be the last argtype")
			else:
				argdecls.append("...")
		else:
			argdecls.append(ffi.getctype(argtype))
	
	return ffi.getctype(restype, "(*)({})".format(",".join(argdecls)))

def _check_argcounts(op, args, argtypes):
	"""Perform sanity checks to ensure that op, args and argtypes are somewhat valid and match each other."""
	
	if not libc.sel_isMapped(op):
		raise ValueError("Invalid selector: {}".format(op))
	
	if not (argtypes and argtypes[-1] is ...):
		if len(args) != len(argtypes):
			raise ValueError("Number of message arguments ({}) doesn't match number of argtypes ({})".format(len(args), len(argtypes)))
		
		sel_arg_count = ffi.string(libc.sel_getName(op)).count(b":")
		if len(args) != sel_arg_count:
			raise ValueError("Number of message arguments ({}) doesn't match number of colons in selector ({})".format(len(args), sel_arg_count))

def _get_polymorphic(name, restype, argtypes):
	"""Get a function pointer for the polymorphic function with the given name, cast to the given restype and argtypes.
	
	If the restype requires use of a different function than normal (such as the _stret version for structures), the correct function is chosen automatically.
	"""
	
	return ffi.cast(_make_function_ptr_ctype(restype, argtypes), getattr(libc, name + "_stret" if _must_use_stret(restype) else name))

# Cache the objc_msgSend function cast to the signatures used for retain and release.
# This is necessary because _gc_release needs to send a release message from within a Python __del__ method.
# Normal _objc_msgSend uses ffi.typeof in multiple places, which internally acquires a (non-reentrant) lock.
# Sometimes the __del__ method is called while the lock is already held, which leads to a deadlock.
# By caching these function pointers beforehand, we don't need to use ffi.typeof later and can avoid the deadlock.
_objc_msgSend_retain = _get_polymorphic("objc_msgSend", ffi.typeof("id"), (ffi.typeof("id"), ffi.typeof("SEL")))
_objc_msgSend_release = _get_polymorphic("objc_msgSend", ffi.typeof("void"), (ffi.typeof("id"), ffi.typeof("SEL")))

def _objc_msgSend(obj, op, *args, restype, argtypes):
	"""Send a message to self with selector op, arguments args, return type restype and argument types argtypes."""
	
	_check_argcounts(op, args, argtypes)
	return _get_polymorphic("objc_msgSend", restype, ("id", "SEL", *argtypes))(obj, op, *args)

def _should_retain_result(sel):
	"""Return whether the object result of the given method should be retained.
	
	According to Objective-C conventions, this is true unless the selector name starts with "copy", "init", "mutableCopy", or "new".
	"""
	
	name = Selector(sel).name_bytes
	return not (
		name.startswith(b"copy")
		or name.startswith(b"init")
		or name.startswith(b"mutableCopy")
		or name.startswith(b"new")
	)

_class_cdata = {
	"NSArray": libc.objc_getClass(b"NSArray"),
	"NSData": libc.objc_getClass(b"NSData"),
	"NSDictionary": libc.objc_getClass(b"NSData"),
	"NSSet": libc.objc_getClass(b"NSSet"),
	"NSString": libc.objc_getClass(b"NSString"),
	"NSValue": libc.objc_getClass(b"NSValue"),
	"Protocol": libc.objc_getClass(b"Protocol"),
}

def _objc_issubclass(subclass, superclass):
	while subclass != ffi.NULL:
		if subclass == superclass:
			return True
		
		cls = libc.class_getSuperclass(subclass)
	
	return False

def _is_protocol(ptr):
	"""Return whether the given id cdata is an instance of Protocol.
	
	This is a primitive internal check that traverses the superclass chain and should only be used when normal isinstance checks are not an option (mainly in ID.__new__ to determine which class to instantiate).
	"""
	
	cls = libc.object_getClass(ptr)
	
	while cls != ffi.NULL:
		if cls == _class_cdata["Protocol"]:
			return True
		
		cls = libc.class_getSuperclass(cls)
	
	return False

def unwrap_cdata(cdata, *, retain=True):
	"""Convert the given cdata object to a more usable object.
	
	id is converted to objc.ID.
	Class is converted to objc.Class or objc.MetaClass.
	Protocol * is converted to objc.Protocol.
	Integers (signed char, short, int, long, long long, and their unsigned versions) is converted to builtins.int.
	float and double is converted to builtins.float.
	char is converted to builtins.bytes.
	bool and BOOL is converted to builtins.bool.
	SEL is converted to objc.Selector.
	Anything else is returned as is.
	"""
	
	if isinstance(cdata, (ffi.typeof("id"), ffi.typeof("Class"), ffi.typeof("Protocol *"))):
		return ID(cdata, retain=retain)
	elif isinstance(cdata, INTEGER_TYPES):
		return int(cdata)
	elif isinstance(cdata, (ffi.typeof("float"), ffi.typeof("double"))):
		return float(cdata)
	elif isinstance(cdata, ffi.typeof("char")):
		return ffi.string(cdata)
	elif isinstance(cdata, ffi.typeof("bool")):
		return bool(cdata)
	elif isinstance(cdata, ffi.typeof("SEL")):
		return Selector(cdata)
	else:
		return cdata

def to_string(s, cls=None):
	if cls is None:
		cls = classes.NSString
	
	return cls.stringWithUTF8String_(s.encode("utf-8"))

def to_data(b, cls=None):
	if cls is None:
		cls = classes.NSData
	
	return cls.dataWithBytes_length_(b, len(b))

def to_array(seq, cls=None):
	if cls is None:
		cls = classes.NSArray
	
	seq = [coerce(x).cdata for x in seq]
	
	return cls.arrayWithObjects_count_(ffi.new("id []", seq), len(seq))

def to_set(seq, cls=None):
	if cls is None:
		cls = classes.NSSet
	
	seq = [coerce(x).cdata for x in seq]
	
	return cls.setWithObjects_count_(ffi.new("id []", seq), len(seq))

def to_dictionary(mapping, cls=None):
	if cls is None:
		cls = classes.NSDictionary
	
	try:
		mapping = mapping.items()
	except AttributeError:
		pass
	
	keys = []
	values = []
	
	for k, v in mapping:
		keys.append(coerce(k).cdata)
		values.append(coerce(v).cdata)
	
	return cls.dictionaryWithObjects_forKeys_count_(ffi.new("id []", values), ffi.new("id []", keys), len(keys))

def coerce(obj, cls=None):
	if isinstance(obj, ID):
		if cls is not None and not _objc_issubclass(obj.cls.cdata, cls.cdata):
			raise TypeError("{obj.cls.name} is not a subclass of {cls.name}".format(obj=obj, cls=cls))
		return obj
	elif cls is None or cls == obj.classes.NSObject:
		if isinstance(obj, str):
			return to_string(obj)
		elif isinstance(obj, bytes):
			return to_data(obj)
		elif isinstance(obj, collections.abc.Mapping):
			return to_dictionary(obj)
		elif isinstance(obj, collections.abc.Set):
			return to_set(obj)
		elif isinstance(obj, collections.abc.Iterable):
			return to_array(obj)
		else:
			raise TypeError("Don't know how to convert a {tp.__module__}.{tp.__qualname__} to an Objective-C object".format(tp=type(obj)))
	elif _objc_issubclass(cls.cdata, _class_cdata["NSString"]):
		return to_string(obj, cls)
	elif _objc_issubclass(cls.cdata, _class_cdata["NSData"]):
		return to_data(obj, cls)
	elif _objc_issubclass(cls.cdata, _class_cdata["NSArray"]):
		return to_array(obj, cls)
	elif _objc_issubclass(cls.cdata, _class_cdata["NSDictionary"]):
		return to_string(obj, cls)
	elif _objc_issubclass(cls.cdata, _class_cdata["NSSet"]):
		return to_set(obj, cls)
	else:
		raise ValueError("Don't know how to convert to an Objective-C {cls.name}".format(cls=cls))

class LazyMapping(collections.abc.Mapping):
	__slots__ = ()
	
	def __repr__(self):
		return "<lazy mapping {cls.__module__}.{cls.__qualname__} at {addr:#x} (use list(mapping.keys()) or list(mapping.items()) to see contents)>".format(cls=type(self), addr=id(self))

class MappingChain(LazyMapping):
	__slots__ = ("_mappings",)
	
	def __init__(self, *mappings):
		super().__init__()
		self._mappings = []
		for mapping in mappings:
			if isinstance(mapping, MappingChain):
				self._mappings += mapping._mappings
			else:
				self._mappings.append(mapping)
		self._mappings.reverse()
	
	def __contains__(self, key):
		for mapping in self._mappings:
			if key in mapping:
				return True
		
		return False
	
	def __getitem__(self, key):
		for mapping in self._mappings:
			try:
				return mapping[key]
			except KeyError:
				pass
		
		raise KeyError(key)
	
	def __iter__(self):
		seen = set()
		for mapping in self._mappings:
			for key in mapping:
				if key not in seen:
					seen.add(key)
					yield key
	
	def __len__(self):
		return sum(len(mapping) for mapping in self._mappings)

class LazyOrderedDict(LazyMapping):
	__slots__ = ("_cached",)
	
	def _get_full(self):
		raise NotImplementedError()
	
	def _get_cached(self):
		try:
			return self._cached
		except AttributeError:
			self._cached = self._get_full()
			return self._cached
	
	def __contains__(self, value):
		return value in self._get_cached()
	
	def __getitem__(self, key):
		return self._get_cached()[key]
	
	def __iter__(self):
		return iter(self._get_cached())
	
	def __len__(self):
		return len(self._get_cached())
	
	def keys(self):
		return self._get_cached().keys()
	
	def items(self):
		return self._get_cached().items()
	
	def values(self):
		return self._get_cached().values()
	
	def __eq__(self, other):
		return self._get_cached() == other
	
	def __ne__(self, other):
		return self._get_cached() != other

class Selector(object):
	"""Represents an Objective-C selector (SEL)."""
	
	_CTYPES = (
		ffi.typeof("SEL"),
		ffi.typeof("void *"),
		int,
	)
	
	__slots__ = ("__weakref__", "cdata")
	
	_cache = weakref.WeakValueDictionary()
	_cache_lock = threading.RLock()
	
	@property
	def name_bytes(self):
		"""The selector's name as bytes."""
		
		return ffi.string(libc.sel_getName(self.cdata))
	
	@property
	def name(self):
		"""The selector's name."""
		
		return self.name_bytes.decode("utf-8")
	
	def __new__(cls, arg):
		"""Create a selector from arg.
		
		If arg is already a Selector, return it unchanged.
		If arg is a str or bytes, create a Selector with that name.
		If arg is a SEL or void * cdata or an int, wrap the SEL at that address. (Selector instances are cached, only one object exists per address.) If the address is NULL, return None. sel_isMapped is used to check whether the address points to a valid SEL, and if not, raise a ValueError.
		"""
		
		if isinstance(arg, cls):
			return arg
		elif isinstance(arg, str):
			return cls(arg.encode("utf-8"))
		elif isinstance(arg, bytes):
			return cls(libc.sel_registerName(arg))
		elif isinstance(arg, Selector._CTYPES):
			arg = ffi.cast("SEL", arg)
			
			if arg == ffi.NULL:
				return None
			else:
				try:
					return cls._cache[arg]
				except KeyError:
					with cls._cache_lock:
						try:
							return cls._cache[arg]
						except KeyError:
							if not libc.sel_isMapped(arg):
								raise ValueError("Not a valid selector: {}".format(arg))
							
							self = super().__new__(cls)
							self.cdata = arg
							cls._cache[arg] = self
							return self
		else:
			raise TypeError("Expected a selector name as a string or bytes, an instance of {cls.__module__}.{cls.__qualname__}, or a SEL-like cdata, not {tp.__module__}.{tp.__qualname__}".format(cls=cls, tp=type(arg)))
	
	def __eq__(self, other):
		return isinstance(other, Selector) and self.cdata == other.cdata
	
	def __ne__(self, other):
		return not isinstance(other, Selector) or self.cdata != other.cdata
	
	def __lt__(self, other):
		if isinstance(other, Selector):
			return self.name_bytes < other.name_bytes
		else:
			return NotImplemented
	
	def __le__(self, other):
		if isinstance(other, Selector):
			return self.name_bytes <= other.name_bytes
		else:
			return NotImplemented
	
	def __ge__(self, other):
		if isinstance(other, Selector):
			return self.name_bytes >= other.name_bytes
		else:
			return NotImplemented
	
	def __gt__(self, other):
		if isinstance(other, Selector):
			return self.name_bytes > other.name_bytes
		else:
			return NotImplemented
	
	def __hash__(self):
		return hash(self.cdata)
	
	def __bytes__(self):
		return self.name_bytes
	
	def __str__(self):
		return self.name
	
	def __repr__(self):
		try:
			name = self.name
		except UnicodeDecodeError:
			name = self.name_bytes
		return "{cls.__module__}.{cls.__qualname__}({name!r})".format(cls=type(self), self=self, name=name)

class Ivar(object):
	"""Represents an Objective-C ivar."""
	
	_CTYPES = (
		ffi.typeof("Ivar"),
		ffi.typeof("void *"),
		int,
	)
	
	__slots__ = ("__weakref__", "_type_cached", "cdata")
	
	_cache = weakref.WeakValueDictionary()
	_cache_lock = threading.RLock()
	
	@property
	def name_bytes(self):
		"""The ivar's name as bytes."""
		
		return ffi.string(libc.ivar_getName(self.cdata))
	
	@property
	def name(self):
		"""The ivar's name."""
		
		return self.name_bytes.decode("utf-8")
	
	@property
	def offset(self):
		"""The position of the start of the ivar's data, in bytes relative to the start of an object."""
		
		return int(libc.ivar_getOffset(self.cdata))
	
	@property
	def type_encoding_bytes(self):
		"""The ivar's type encoding as bytes."""
		
		return ffi.string(libc.ivar_getTypeEncoding(self.cdata))
	
	@property
	def type_encoding(self):
		"""The ivar's type encoding."""
		
		return self.type_encoding_bytes.decode("utf-8")
	
	@property
	def type(self):
		"""The ivar's type as a CFFI type."""
		
		try:
			return self._type_cached
		except AttributeError:
			self._type_cached = _encoding_type_to_cffi(encoding.decode(self.type_encoding))
			return self._type_cached
	
	def __new__(cls, arg):
		"""Create an Ivar from the given arg.
		
		If arg is already an Ivar, return it unchanged.
		If arg is an Ivar or void * cdata or an int, wrap the Ivar at that address. (Ivar instances are cached, only one object exists per address.) If the address is NULL, return None.
		"""
		
		if isinstance(arg, cls):
			return arg
		elif isinstance(arg, Ivar._CTYPES):
			arg = ffi.cast("Ivar", arg)
			
			if arg == ffi.NULL:
				return None
			else:
				try:
					return cls._cache[arg]
				except KeyError:
					with cls._cache_lock:
						try:
							return cls._cache[arg]
						except KeyError:
							self = super().__new__(cls)
							self.cdata = arg
							cls._cache[arg] = self
							return self
		else:
			raise TypeError("Expected an instance of {cls.__module__}.{cls.__qualname__}, or an Ivar-like cdata, not {tp.__module__}.{tp.__qualname__}".format(cls=cls, tp=type(arg)))
	
	def __eq__(self, other):
		return isinstance(other, Ivar) and self.cdata == other.cdata
	
	def __ne__(self, other):
		return not isinstance(other, Ivar) or self.cdata != other.cdata
	
	def __repr__(self):
		try:
			name = self.name
		except UnicodeDecodeError:
			name = self.name_bytes
		return "<{cls.__module__}.{cls.__qualname__} {name!r}, type {self.type_encoding_bytes!r}, offset 0x{self.offset:x}>".format(cls=type(self), self=self, name=name)
	
	def _get_pointer(self, base):
		"""Create a pointer to this ivar's data in the object pointed to by base."""
		
		return ffi.cast(ffi.getctype(self.type, "*"), ffi.cast("char *", base) + self.offset)
	
	def get(self, instance):
		"""Get the value of this ivar in the given object. Only use when you're desperate, you should normally use public properties or methods to get an object's data."""
		
		return unwrap_cdata(self._get_pointer(instance.cdata)[0])
	
	def set(self, instance, value):
		"""Set the value of this ivar in the given object. Only use when you're REALLY desperate, you'll probably break things if you use this instead of public properties or methods to set an object's data."""
		
		if isinstance(value, ID):
			value = value.cdata
		
		self._get_pointer(instance.cdata)[0] = ffi.cast(self.type, value)

class Method(object):
	"""Represents an Objective-C method."""
	
	_CTYPES = (
		ffi.typeof("Method"),
		ffi.typeof("void *"),
		int,
	)
	
	__slots__ = ("__weakref__", "cdata")
	
	_cache = weakref.WeakValueDictionary()
	_cache_lock = threading.RLock()
	
	@property
	def argument_count(self):
		"""The number of arguments that this method takes."""
		
		return int(libc.method_getNumberOfArguments(self.cdata))
	
	@property
	def implementation(self):
		"""The method's implementation as a C function pointer."""
		
		return libc.method_getImplementation(self.cdata)
	
	@implementation.setter
	def implementation(self, implementation):
		libc.method_setImplementation(self.cdata, implementation)
	
	@property
	def selector(self):
		"""The method's selector."""
		
		return Selector(libc.method_getName(self.cdata))
	
	@property
	def type_encoding_bytes(self):
		"""The method's type encoding as bytes."""
		
		return ffi.string(libc.method_getTypeEncoding(self.cdata))
	
	@property
	def type_encoding(self):
		"""The method's type encoding."""
		
		return self.type_encoding_bytes.decode("utf-8")
	
	def __new__(cls, arg):
		"""Create a Method from the given arg.
		
		If arg is already a Method, return it unchanged.
		If arg is a Method or void * cdata or an int, wrap the Method at that address. (Method instances are cached, only one object exists per address.) If the address is NULL, return None.
		"""
		
		if isinstance(arg, cls):
			return arg
		elif isinstance(arg, Method._CTYPES):
			arg = ffi.cast("Method", arg)
			
			if arg == ffi.NULL:
				return None
			else:
				try:
					return cls._cache[arg]
				except KeyError:
					with cls._cache_lock:
						try:
							return cls._cache[arg]
						except KeyError:
							self = super().__new__(cls)
							self.cdata = arg
							cls._cache[arg] = self
							return self
		else:
			raise TypeError("Expected an instance of {cls.__module__}.{cls.__qualname__}, or a Method-like cdata, not {tp.__module__}.{tp.__qualname__}".format(cls=cls, tp=type(arg)))
	
	def __eq__(self, other):
		return isinstance(other, Method) and self.cdata == other.cdata
	
	def __ne__(self, other):
		return not isinstance(other, Method) or self.cdata != other.cdata
	
	def __repr__(self):
		try:
			name = self.selector.name
		except UnicodeDecodeError:
			name = self.selector.name_bytes
		
		return "<{cls.__module__}.{cls.__qualname__} {name!r}, signature {self.type_encoding_bytes!r}>".format(cls=type(self), self=self, name=name)
	
	def __call__(self, receiver, *args, restype=None, argtypes=None):
		receiver = ID(receiver)
		sel = Selector(sel)
		if argtypes is None and restype is None:
			restype, argtypes = self.decode_signature()
		elif argtypes is None or restype is None:
			raise ValueError("restype and argtypes must be passed together")
		else:
			if isinstance(restype, str):
				restype = ffi.typeof(restype)
			
			argtypes = [ffi.typeof(at) if isinstance(at, str) else at for at in argtypes]
		
		return unwrap_cdata(
			_get_polymorphic("method_invoke", restype, ("id", "Method", *argtypes))(receiver.cdata, self.cdata, *args),
			retain=_should_retain_result(sel),
		)
	
	def decode_signature_raw(self):
		"""Decode the method's signature into a tuple (restype, argtypes) of objc.encoding types."""
		
		restype, argtypes = encoding.decode_method_signature(self.type_encoding)
		# Use argtypes[2:] to skip the first two argtypes (self and _cmd)
		return restype, argtypes[2:]
	
	def decode_signature(self):
		"""Decode the method's signature into a tuple (restype, argtypes) of CFFI types."""
		
		restype, argtypes = self.decode_signature_raw()
		return _encoding_type_to_cffi(restype), [_encoding_type_to_cffi(argtype) for argtype in argtypes]
	
	def exchange_implementations(self, other):
		"""Atomically exchange the implementation of this method with that of the given other method."""
		
		if not isinstance(other, Method):
			raise TypeError("other must be a Method, not {tp.__module__}.{tp.__qualname__}".format(tp=type(other)))
		
		libc.method_exchangeImplementations(self.cdata, other.cdata)

class BoundMethod(object):
	"""A Method bound to an ID, which can be called directly."""
	
	__slots__ = ("__weakref__", "instance", "selector")
	
	@property
	def method(self):
		"""The method object for this bound method, derived from the selector and instance type.
		
		Note that this property is not used when calling a bound method - this is done using msg_send on the instance, to call dynamic methods correctly. This property is mainly meant for convenient introspection of a bound method's implementation, and is for example used in BoundMethod's __repr__ implementation.
		"""
		
		return self.instance.cls.instance_methods[self.selector]
	
	def __new__(cls, instance, selector):
		"""Create a BoundMethod for the given instance and selector."""
		
		self = super().__new__(cls)
		
		if not isinstance(instance, ID):
			raise TypeError("instance must be an ID instance, not {tp.__module__}.{tp.__qualname__}".format(tp=type(instance)))
		
		self.instance = instance
		self.selector = Selector(selector)
		
		return self
	
	def __eq__(self, other):
		return isinstance(other, BoundMethod) and self.instance is other.instance and self.selector == other.selector
	
	def __ne__(self, other):
		return not isinstance(other, BoundMethod) or self.instance is not other.instance or self.selector != other.selector
	
	def __repr__(self):
		try:
			name = self.selector.name
		except UnicodeDecodeError:
			name = self.selector.name_bytes
		
		try:
			meth = self.method
		except KeyError:
			meth = "<method not found on class>"
		
		return "<{cls.__module__}.{cls.__qualname__} {name!r} of {self.instance.cls.name} instance: {meth}>".format(cls=type(self), self=self, name=name, meth=meth)
	
	def __call__(self, *args, **kwargs):
		"""Call this method on the instance it is bound to."""
		
		return self.instance.msg_send(self.selector, *args, **kwargs)

class Property(object):
	"""Represents an Objective-C property."""
	
	_CTYPES = (
		ffi.typeof("objc_property_t"),
		ffi.typeof("void *"),
		int,
	)
	
	__slots__ = ("__weakref__", "_attributes_cached", "_type_cached", "cdata")
	
	_cache = weakref.WeakValueDictionary()
	_cache_lock = threading.RLock()
	
	@property
	def name_bytes(self):
		"""The property's name as bytes."""
		
		return ffi.string(libc.property_getName(self.cdata))
	
	@property
	def name(self):
		"""The property's name."""
		
		return self.name_bytes.decode("utf-8")
	
	@property
	def attribute_encoding_bytes(self):
		"""The property's attribute encoding as bytes."""
		
		return ffi.string(libc.property_getAttributes(self.cdata))
	
	@property
	def attribute_encoding(self):
		"""The property's attribute encoding."""
		
		return self.attribute_encoding_bytes.decode("utf-8")
	
	@property
	def attributes(self):
		"""The property's attribute encoding as an objc.encoding.Property object."""
		
		try:
			return self._attributes_cached
		except AttributeError:
			self._attributes_cached = encoding.decode_property(self.attribute_encoding)
			return self._attributes_cached
	
	@property
	def type(self):
		"""The property's type as a CFFI type."""
		
		try:
			return self._type_cached
		except AttributeError:
			self._type_cached = _encoding_type_to_cffi(self.attributes.type)
			return self._type_cached
	
	@property
	def readonly(self):
		"""Whether this property is read-only."""
		
		return self.attributes.readonly
	
	@property
	def getter(self):
		"""The getter selector."""
		
		sel = self.attributes.getter
		if sel is None:
			sel = self.name
		return Selector(sel)
	
	@property
	def setter(self):
		"""The setter selector, or None if this property is read-only."""
		
		if self.readonly:
			return None
		
		sel = self.attributes.setter
		if sel is None:
			sel = "set{}{}:".format(self.name[0].upper(), self.name[1:])
		return Selector(sel)
	
	def __new__(cls, arg):
		"""Create a Property from the given arg.
		
		If arg is already a Property, return it unchanged.
		If arg is an objc_property_t or void * cdata or an int, wrap the objc_property_t at that address. (Property instances are cached, only one object exists per address.) If the address is NULL, return None.
		"""
		
		if isinstance(arg, cls):
			return arg
		elif isinstance(arg, Property._CTYPES):
			arg = ffi.cast("objc_property_t", arg)
			
			if arg == ffi.NULL:
				return None
			else:
				try:
					return cls._cache[arg]
				except KeyError:
					with cls._cache_lock:
						try:
							return cls._cache[arg]
						except KeyError:
							self = super().__new__(cls)
							self.cdata = arg
							cls._cache[arg] = self
							return self
		else:
			raise TypeError("Expected an instance of {cls.__module__}.{cls.__qualname__}, or an objc_property_t-like cdata, not {tp.__module__}.{tp.__qualname__}".format(cls=cls, tp=type(arg)))
	
	def __eq__(self, other):
		return isinstance(other, Property) and self.cdata == other.cdata
	
	def __ne__(self, other):
		return not isinstance(other, Property) or self.cdata != other.cdata
	
	def __repr__(self):
		try:
			name = self.name
		except UnicodeDecodeError:
			name = self.name_bytes
		return "<{cls.__module__}.{cls.__qualname__} {name!r}, attributes {self.attribute_encoding_bytes!r}>".format(cls=type(self), self=self, name=name)
	
	def get(self, instance, **kwargs):
		"""Get the value of this property on the given instance. Internally this sends the getter selector to the instance. Any keyword arguments are passed on to instance.msg_send."""
		
		return instance.msg_send(self.getter, **kwargs)
	
	def set(self, instance, value, **kwargs):
		"""Set the value of this property on the given instance. If this property is read-only, raise a TypeError. Internally this sends the setter selector with the value as an argument to the instance. Any keyword arguments are passed on to instance.msg_send."""
		
		if self.readonly:
			raise TypeError("Cannot set the value of read-only property {self.name_bytes!r}".format(self=self))
		
		return instance.msg_send(self.setter, value, **kwargs)

class ID(object):
	"""Represents an Objective-C instance.
	
	This class has subclasses Class, MetaClass and Protocol, which are automatically used instead of ID when wrapping an object of one of their types.
	"""
	
	class _Methods(LazyOrderedDict):
		__slots__ = ("_instance",)
		
		def __init__(self, instance):
			super().__init__()
			self._instance = instance
		
		def _get_full(self):
			return collections.OrderedDict((sel, BoundMethod(self._instance, sel)) for sel in self._instance.cls.instance_methods.keys())
		
		def __getitem__(self, key):
			self._instance.cls.instance_methods[key] # Cause a KeyError if the method is not valid
			return BoundMethod(self._instance, key)
	
	class _Properties(LazyOrderedDict):
		__slots__ = ("_instance",)
		
		def __init__(self, instance):
			super().__init__()
			self._instance = instance
		
		def _get_full(self):
			return collections.OrderedDict((name, prop.get(self._instance)) for name, prop in self._instance.cls.instance_properties.items())
		
		def __getitem__(self, key):
			return self._instance.cls.instance_properties[key].get(self._instance)
		
		def __setitem__(self, key, value):
			return self._instance.cls.instance_properties[key].set(self._instance, value)
	
	_CTYPES = (
		ffi.typeof("id"), # Protocol * is equivalent to id
		ffi.typeof("Class"),
		ffi.typeof("void *"),
		int,
	)
	
	__slots__ = ("__weakref__", "_methods_cache", "cdata", "methods", "properties")
	
	_cache = weakref.WeakValueDictionary()
	_cache_lock = threading.RLock()
	
	@property
	def _objc_ptr(self):
		return int(ffi.cast("uintptr_t", self.cdata))
	
	@property
	def cls(self):
		"""The object's class."""
		return Class(libc.object_getClass(self.cdata))
	
	def __new__(cls, arg, *, retain=True):
		"""Create an ID from arg.
		
		If arg is already an ID instance, it is returned unchanged.
		If arg is an id, Class, or void * cdata, or a Python int, wrap the object at that address. (ID instances are cached, only one object exists per address.) If the pointer is NULL, return None instead.
		
		The ID constructor returns a subclass (such as Class or Protocol) if appropriate. If an ID subclass is instantiated and the given object is of a different type, a TypeError is raised. Calling ID is guaranteed to succeed as long as arg is an ID instance or a valid object pointer.
		
		By default, the wrapped object is retained/released automatically when the ID is created/garbage-collected. The initial retain can be suppressed by setting the retain kwarg to False, however this is usually done by the method calling mechanisms if necessary and rarely needs to be done by hand. No matter what the value of retain is, the object is always released when the ID wrapper is garbage-collected.
		"""
		
		# Technical details on the retain/release cycle:
		# When a new ID instance is created (rather than obtained from the cache) and retain is true, the underlying object is retained once. If retain is false, nothing happens and it is assumed that the underlying object is already owned.
		# When the ID constructor returns an existing ID instance (rather than creating a new one) and retain is true, nothing happens, since the underlying object is already owned. If retain is false, the underlying object is *released* once. This is done to balance the retain that must have happened before.
		# These rules mean that any object wrapped by an ID always has one "active retention" during its lifetime. When an ID instance is garbage-collected, the underlying object is released exactly once.
		
		if isinstance(arg, cls):
			# Special case: if arg is already an instance of cls, return it unchanged.
			if not retain:
				_release(arg.cdata)
			return arg
		elif isinstance(arg, ID._CTYPES):
			# Create an ID from a cdata.
			arg = ffi.cast("id", arg)
			
			if arg == ffi.NULL:
				return None
			
			if not issubclass(cls, Class) and libc.object_isClass(arg):
				# If arg points to a class, return a Class instead.
				return Class(ffi.cast("Class", arg), retain=retain)
			elif not issubclass(cls, Protocol) and _is_protocol(arg):
				# If arg points to a Protocol, return a Protocol instead.
				return Protocol(ffi.cast("Protocol *", arg), retain=retain)
			else:
				# See if we already have an instance cached, otherwise create one.
				try:
					self = cls._cache[arg]
					if not retain:
						_release(self.cdata)
					return self
				except KeyError:
					with cls._cache_lock:
						try:
							self = cls._cache[arg]
							if not retain:
								_release(self.cdata)
							return self
						except KeyError:
							self = super().__new__(cls)
							object.__setattr__(self, "cdata", _gc_release(arg))
							if retain:
								_retain(arg)
							cls._cache[arg] = self
							object.__setattr__(self, "methods", ID._Methods(self))
							object.__setattr__(self, "properties", ID._Properties(self) if SHORT_PROPERTIES else {})
							object.__setattr__(self, "_methods_cache", weakref.WeakValueDictionary())
							return self
		elif isinstance(arg, (objc_util.ObjCInstance, objc_util.ObjCClass)):
			return ID(arg.ptr, retain=retain)
		elif isinstance(arg, ctypes.c_void_p):
			return ID(arg.value)
		else:
			try:
				addr = arg._objc_ptr
			except AttributeError:
				raise TypeError("Expected an instance of objc.ID, objc_util.ObjCInstance, or objc_util.ObjCClass, an id-like cdata, or an object with _objc_ptr, not {tp.__module__}.{tp.__qualname__}".format(tp=type(arg)))
			else:
				return ID(addr, retain=retain)
				
		assert False, "Someone forgot to return a thing"
	
	def __getattr__(self, name):
		try:
			return self.properties[name]
		except KeyError:
			try:
				return self.methods[name.replace("_", ":")]
			except KeyError:
				raise AttributeError(name)
	
	def __setattr__(self, name, value):
		try:
			self.cdata
		except AttributeError:
			super().__setattr__(name, value)
		else:
			if self.cls._instance_property_names is None:
				# Lazy init of _instance_property_names. This can't be done in __new__, because at that point self.cls may not exist yet because of metaclasses and stuff.
				self.cls._instance_property_names = {prop.name for prop in self.cls.instance_properties}
			
			try:
				# Check if a real attribute with this name exists.
				object.__getattribute__(self, name)
			except AttributeError:
				# If not, try setting a property, and fall back to normal __setattr__ otherwise.
				if name in self.cls._instance_property_names:
					self.properties[name] = value
				else:
					super().__setattr__(name, value)
			else:
				# If a read attribute with this name does exist, always use normal __setattr__, so our own attribute setting won't break because of a badly named Objective-C property.
				super().__setattr__(name, value)
	
	def __dir__(self):
		return {
			*super().__dir__(),
			*(name.replace(":", "_") for name in self.cls.instance_attr_names_public),
		}
	
	def __repr__(self):
		try:
			clsname = self.cls.name
		except UnicodeDecodeError:
			clsname = self.cls.name_bytes
		
		return "<{cls.__module__}.{cls.__qualname__} wrapping {clsname} at {self.cdata!r}: {desc}>".format(
			cls=type(self),
			self=self,
			clsname=clsname,
			desc=ffi.string(self.msg_send("debugDescription").msg_send("UTF8String")).decode("utf-8"),
		)
	
	def __eq__(self, other):
		return isinstance(other, ID) and self.cdata == other.cdata
	
	def __ne__(self, other):
		return not isinstance(other, ID) or self.cdata != other.cdata
	
	def responds_to(self, sel):
		"""Return whether this object responds to the given selector.
		
		This method first checks (using the instances_respond_to_api method on this object's class) whether this object responds to the respondsToSelector: selector. If so, that selector is used to check whether this object responds to sel, otherwise this object's instances_respond_to method is used to do the same.
		"""
		
		sel = Selector(sel)
		
		if self.cls.instances_respond_to(b"respondsToSelector:"):
			return bool(self.msg_send(b"respondsToSelector:", sel, check_responds=False))
		else:
			return self.cls.instances_respond_to(sel)
	
	def msg_send(self, sel, *args, restype=None, argtypes=None, check_responds=True):
		"""Send the given selector and arguments to this instance.
		
		restype and argtypes may be used to manually set the method's argument and return types, otherwise the types are decoded from the method's type encoding.
		"""
		
		sel = Selector(sel)
		
		if check_responds and not self.responds_to(sel):
			if isinstance(self, MetaClass):
				raise ValueError("Metaclass {self.name} does not respond to selector {sel.name_bytes!r}".format(self=self, sel=sel))
			elif isinstance(self, Class):
				raise ValueError("Class {self.name} does not respond to selector {sel.name_bytes!r}".format(self=self, sel=sel))
			else:
				raise ValueError("{self.cls.name} instance at {self.cdata} does not respond to selector {sel.name_bytes!r}".format(self=self, sel=sel))
		
		if argtypes is None and restype is None:
			try:
				method = self.cls.instance_methods[sel]
			except KeyError:
				raise ValueError("No method found for selector {sel.name_bytes!r}, cannot infer restype and argtypes".format(sel=sel))
			else:
				restype, argtypes = method.decode_signature()
		elif argtypes is None or restype is None:
			raise ValueError("restype and argtypes must be passed together")
		else:
			if isinstance(restype, str):
				restype = ffi.typeof(restype)
			
			argtypes = [ffi.typeof(at) if isinstance(at, str) else at for at in argtypes]
		
		new_args = []
		for arg, tp in zip(args, argtypes):
			if isinstance(arg, Class) and issubclass(tp, ffi.typeof("Class")):
				new_args.append(ffi.cast("Class", arg.cdata))
			elif isinstance(arg, (ID, Selector)):
				new_args.append(arg.cdata)
			elif issubclass(tp, ffi.typeof("id")):
				try:
					new_args.append(coerce(arg).cdata)
				except TypeError:
					new_args.append(arg)
			else:
				new_args.append(arg)
		
		return unwrap_cdata(
			_objc_msgSend(ffi.cast("id", self.cdata), sel.cdata, *new_args, restype=restype, argtypes=argtypes),
			retain=_should_retain_result(sel),
		)

class Class(ID):
	class _InstanceIvarsDeclared(LazyOrderedDict):
		__slots__ = ("_cls",)
		
		def __init__(self, cls):
			super().__init__()
			self._cls = cls
		
		def _get_full(self):
			count_ptr = ffi.new("unsigned int *")
			ivars_ptr = gc_free(libc.class_copyIvarList(ffi.cast("Class", self._cls.cdata), count_ptr))
			ivars = (Ivar(ivars_ptr[i]) for i in range(count_ptr[0]))
			return collections.OrderedDict((ivar.name_bytes, ivar) for ivar in ivars)
		
		def __getitem__(self, key):
			if isinstance(key, str):
				return self[key.encode("utf-8")]
			elif not isinstance(key, bytes):
				raise TypeError("{cls.__module__}.{cls.__qualname__} keys must be str or bytes".format(cls=type(self)))
			
			ivar = libc.class_getInstanceVariable(ffi.cast("Class", self._cls.cdata), key)
			if ivar == ffi.NULL:
				raise KeyError(key)
			return Ivar(ivar)
	
	class _InstanceMethods(MappingChain):
		__slots__ = ("_cls",)
		
		def __init__(self, cls):
			if cls.superclass is None:
				super().__init__(cls.instance_methods_declared)
			else:
				super().__init__(cls.superclass.instance_methods, cls.instance_methods_declared)
			self._cls = cls
		
		def __contains__(self, key):
			return libc.class_getInstanceMethod(ffi.cast("Class", self._cls.cdata), Selector(key).cdata) != ffi.NULL
		
		def __getitem__(self, key):
			method = libc.class_getInstanceMethod(ffi.cast("Class", self._cls.cdata), Selector(key).cdata)
			if method == ffi.NULL:
				raise KeyError(key)
			return Method(method)
	
	class _InstanceMethodsDeclared(LazyOrderedDict):
		__slots__ = ("_cls",)
		
		def __init__(self, cls):
			super().__init__()
			self._cls = cls
		
		def _get_full(self):
			count_ptr = ffi.new("unsigned int *")
			methods_ptr = gc_free(libc.class_copyMethodList(ffi.cast("Class", self._cls.cdata), count_ptr))
			methods = (Method(methods_ptr[i]) for i in range(count_ptr[0]))
			return collections.OrderedDict((method.selector, method) for method in methods)
		
		def __getitem__(self, key):
			return self._get_cached()[Selector(key)]
	
	class _InstancePropertiesDeclared(LazyOrderedDict):
		__slots__ = ("_cls",)
		
		def __init__(self, cls):
			super().__init__()
			self._cls = cls
		
		def _get_full(self):
			count_ptr = ffi.new("unsigned int *")
			properties_ptr = gc_free(libc.class_copyPropertyList(ffi.cast("Class", self._cls.cdata), count_ptr))
			properties = (Property(properties_ptr[i]) for i in range(count_ptr[0]))
			return collections.OrderedDict((prop.name_bytes, prop) for prop in properties)
		
		def __getitem__(self, key):
			if isinstance(key, str):
				key = key.encode("utf-8")
			
			if not isinstance(key, bytes):
				raise TypeError("{cls.__module__}.{cls.__qualname__} keys must be str or bytes".format(cls=type(self)))
			
			prop = libc.class_getProperty(ffi.cast("Class", self._cls.cdata), key)
			if prop == ffi.NULL:
				raise KeyError(key)
			return Property(prop)
	
	_CTYPES = (
		ffi.typeof("Class"),
		ffi.typeof("void *"),
		int,
	)
	
	__slots__ = ("_instance_property_names", "instance_ivars_declared", "instance_methods", "instance_methods_declared", "instance_properties_declared")
	
	@property
	def name_bytes(self):
		return ffi.string(libc.class_getName(ffi.cast("Class", self.cdata)))
	
	@property
	def name(self):
		return self.name_bytes.decode("utf-8")
	
	@property
	def instance_size(self):
		return int(libc.class_getInstanceSize(ffi.cast("Class", self.cdata)))
	
	@property
	def instance_ivars(self):
		if self.superclass is None:
			return self.instance_ivars_declared
		else:
			return MappingChain(self.superclass.instance_ivars, self.instance_ivars_declared)
	
	@property
	def instance_attr_names_public(self):
		if self.superclass is None:
			names = set()
		else:
			names = self.superclass.instance_attr_names_public
		
		try:
			class_methods, instance_methods = data.PUBLIC_CLASS_METHODS[self.name]
		except (KeyError, UnicodeDecodeError):
			for sel in self.instance_methods_declared:
				try:
					name = sel.name
				except UnicodeDecodeError:
					continue
				
				##if not name.startswith("_"):
				# Only include names that contain no underscores.
				# This is necessary because the current method lookup algorithm simply replaces every _ with a : and tries to find a method with that name.
				# This fails for methods that contain underscores in their name.
				# As a nice side effect, this also hides any "private" methods (starting with an underscore).
				if "_" not in name:
					names.add(name)
			
			if SHORT_PROPERTIES:
				for prop in self.instance_properties_declared.values():
					try:
						names.discard(prop.getter.name)
					except ValueError:
						print("Failed to get getter for property {}".format(prop))
					except (AttributeError, UnicodeDecodeError):
						pass
					
					try:
						names.discard(prop.setter.name)
					except ValueError:
						print("Failed to get setter for property {}".format(prop))
					except (AttributeError, UnicodeDecodeError):
						pass
				
				for prop in self.instance_properties_declared.values():
					try:
						if "_" not in prop.name and "_" not in prop.getter.name and self.instances_respond_to(prop.getter):
							names.add(prop.name)
					except UnicodeDecodeError:
						pass
		else:
			names.update(class_methods if isinstance(self, MetaClass) else instance_methods)
		
		return names
	
	@property
	def instance_properties(self):
		if self.superclass is None:
			return self.instance_properties_declared
		else:
			return MappingChain(self.superclass.instance_properties, self.instance_properties_declared)
	
	@property
	def protocols(self):
		count_ptr = ffi.new("unsigned int *")
		protocols_ptr = gc_free(libc.class_copyProtocolList(ffi.cast("Class", self.cdata), count_ptr))
		ps = [Protocol(protocols_ptr[i]) for i in range(count_ptr[0])]
		return ps
	
	@property
	def superclass(self):
		return Class(libc.class_getSuperclass(ffi.cast("Class", self.cdata)))
	
	@property
	def version(self):
		return int(libc.class_getVersion(ffi.cast("Class", self.cdata)))
	
	def __new__(cls, arg, retain=True):
		if isinstance(arg, cls):
			if not retain:
				_release(arg.cdata)
			return arg
		elif isinstance(arg, str):
			return cls(arg.encode("utf-8"), retain=retain)
		elif isinstance(arg, bytes):
			cdata = libc.objc_getClass(arg)
			if cdata == ffi.NULL:
				raise ValueError("No class named {}".format(arg))
			return cls(cdata, retain=retain)
		elif isinstance(arg, Class._CTYPES):
			arg = ffi.cast("id", arg)
			
			if arg == ffi.NULL:
				return None
			elif not libc.object_isClass(arg):
				raise ValueError("{!r} does not point to a class")
			elif not issubclass(cls, MetaClass) and libc.class_isMetaClass(ffi.cast("Class", arg)):
				# If arg points to a metaclass, return a MetaClass instead.
				return MetaClass(ffi.cast("Class", arg), retain=retain)
			else:
				self = super().__new__(cls, arg, retain=retain)
				
				try:
					object.__getattribute__(self, "_instance_property_names")
				except AttributeError:
					##self._instance_property_names = {prop.name for prop in self.instance_properties.values()}
					object.__setattr__(self, "_instance_property_names", None)
				
				try:
					object.__getattribute__(self, "instance_ivars_declared")
				except AttributeError:
					object.__setattr__(self, "instance_ivars_declared", Class._InstanceIvarsDeclared(self))
					object.__setattr__(self, "instance_methods_declared", Class._InstanceMethodsDeclared(self))
					object.__setattr__(self, "instance_methods", Class._InstanceMethods(self))
					object.__setattr__(self, "instance_properties_declared", Class._InstancePropertiesDeclared(self))
				
				return self
		elif isinstance(arg, objc_util.ObjCClass):
			return Class(arg.ptr)
		elif isinstance(arg, ctypes.c_void_p):
			return Class(arg.value)
		else:
			raise TypeError("Expected a class name as str or bytes, an instance of {cls.__module__}.{cls.__qualname__} or objc_util.ObjCClass, or a Class-like cdata, not {tp.__module__}.{tp.__qualname__}".format(cls=cls, tp=type(arg)))
				
		assert False, "Someone forgot to return a thing"
	
	def __repr__(self):
		try:
			name = self.name
		except UnicodeDecodeError:
			name = self.name_bytes
		return "{cls.__module__}.{cls.__qualname__}({name!r})".format(cls=type(self), self=self, name=name)
	
	def __subclasscheck__(self, subclass):
		if not isinstance(subclass, Class):
			raise TypeError("Argument 1 of issubclass(arg, {cls.__module__}.{cls.__qualname__}()) must be an objc.Class, not {tp.__module__}.{tp.__qualname__}".format(cls=type(self), tp=type(subclass)))
		
		if subclass.cls.instances_respond_to_api("isSubclassOfClass:"):
			return bool(subclass.msg_send("isSubclassOfClass:", self))
		else:
			while subclass is not None:
				if self == subclass:
					return True
				
				subclass = subclass.superclass
			
			return False
	
	def __instancecheck__(self, instance):
		if isinstance(instance, ID):
			if instance.cls.instances_respond_to_api("isKindOfClass:"):
				return bool(instance.msg_send("isKindOfClass:", self))
			else:
				return issubclass(instance.cls, self)
		else:
			return False
	
	def instances_respond_to_api(self, sel):
		"""Return whether instances of this class respond to the given selector, by asking the Objective-C runtime API rather than sending an instancesRespondToSelector: message.
		
		In almost all cases the instances_respond_to method should be used instead of this method.
		"""
		
		sel = Selector(sel)
		return bool(libc.class_respondsToSelector(ffi.cast("Class", self.cdata), sel.cdata))
	
	def instances_respond_to(self, sel):
		"""Return whether instances of this class respond to the given selector.
		
		This method first checks (using the instances_respond_to_api method on this class's metaclass) whether this class responds to the instancesRespondToSelector: selector. If so, that selector is used to check whether instances of this class respond to sel, otherwise the instances_respond_to_api method is used to do the same.
		"""
		
		sel = Selector(sel)
		if self.cls.instances_respond_to_api(b"instancesRespondToSelector:"):
			return bool(self.msg_send(b"instancesRespondToSelector:", sel, check_responds=False))
		else:
			return self.instances_respond_to_api(sel)

class MetaClass(Class):
	__slots__ = ()
	
	def __new__(cls, arg, retain=True):
		if isinstance(arg, cls):
			if not retain:
				_release(arg.cdata)
			return arg
		elif isinstance(arg, (bytes, str)):
			self = Class(arg).cls
			if not retain:
				_release(self.cdata)
			return self
		elif isinstance(arg, MetaClass._CTYPES):
			arg = ffi.cast("id", arg)
			
			if arg == ffi.NULL:
				return None
			elif not libc.object_isClass(arg) or not libc.class_isMetaClass(ffi.cast("Class", arg)):
				raise ValueError("Object pointer {!r} must point to a metaclass".format(arg))
			else:
				return super().__new__(cls, ffi.cast("Class", arg), retain=retain)
		else:
			raise TypeError("Expected a class name as str or bytes, a {cls.__module__}.{cls.__qualname__} instance, or a Class-like cdata, not {tp.__module__}.{tp.__qualname__}".format(cls=cls, tp=type(arg)))
				
		assert False, "Someone forgot to return a thing"

class Protocol(ID):
	_CTYPES = (
		ffi.typeof("id"), # Equivalent to Protocol *
		ffi.typeof("void *"),
		int,
	)
	
	__slots__ = ()
	
	@property
	def name_bytes(self):
		return ffi.string(libc.protocol_getName(ffi.cast("Protocol *", self.cdata)))
	
	@property
	def name(self):
		return self.name_bytes.decode("utf-8")
	
	@property
	def protocols(self):
		count_ptr = ffi.new("unsigned int *")
		protocols_ptr = gc_free(libc.protocol_copyProtocolList(ffi.cast("Protocol *", self.cdata), count_ptr))
		return [Protocol(protocols_ptr[i]) for i in range(count_ptr[0])]
		return []
	
	def __new__(cls, arg, retain=True):
		if isinstance(arg, cls):
			if not retain:
				_release(arg.cdata)
			return arg
		elif isinstance(arg, str):
			return cls(arg.encode("utf-8"), retain=retain)
		elif isinstance(arg, bytes):
			cdata = libc.objc_getProtocol(arg)
			if cdata == ffi.NULL:
				raise ValueError("No protocol named {}".format(arg))
			return cls(cdata, retain=retain)
		elif isinstance(arg, Protocol._CTYPES):
			arg = ffi.cast("id", arg)
			
			if arg == ffi.NULL:
				return None
			elif not _is_protocol(arg):
				raise ValueError("Object pointer {arg!r} must point to a Protocol instance".format(arg=arg, self=self))
			else:
				return super().__new__(cls, arg, retain=retain)
		else:
			raise TypeError("Expected a protocol name as str or bytes, a {cls.__module__}.{cls.__qualname__} instance, or a Protocol *-like cdata, not {tp.__module__}.{tp.__qualname__}".format(cls=cls, tp=type(arg)))
				
		assert False, "Someone forgot to return a thing"
	
	def __repr__(self):
		try:
			name = self.name
		except UnicodeDecodeError:
			name = self.name_bytes
		return "{cls.__module__}.{cls.__qualname__}({name!r})".format(cls=type(self), self=self, name=name)
	
	def __eq__(self, other):
		return isinstance(other, Protocol) and bool(libc.protocol_isEqual(ffi.cast("Protocol *", self.cdata), ffi.cast("Protocol *", other.cdata)))
	
	def __ne__(self, other):
		return not isinstance(other, Protocol) or not libc.protocol_isEqual(ffi.cast("Protocol *", self.cdata), ffi.cast("Protocol *", other.cdata))
	
	def __subclasscheck__(self, subclass):
		# Of course class_conformsToProtocol doesn't recursively check the superclass and adopted protocols, so we need to do that ourselves.
		if isinstance(subclass, Class):
			# Use the conformsToProtocol: method if possible.
			if subclass.cls.instances_respond_to_api("conformsToProtocol:"):
				return bool(subclass.msg_send("conformsToProtocol:", self))
			
			# See if subclass adopts self directly.
			if libc.class_conformsToProtocol(ffi.cast("Class", subclass.cdata), ffi.cast("Protocol *", self.cdata)):
				return True
			
			# If subclass has a superclass, see if it conforms (directly or indirectly) to self.
			if subclass.superclass is not None and issubclass(subclass.superclass, self):
				return True
			
			# See if any of the protocols directly adopted by subclass conform (directly or indirectly) to self.
			for proto in subclass.protocols:
				if issubclass(proto, self):
					return True
			
			return False
		elif isinstance(subclass, Protocol):
			# See if subclass adopts self directly.
			if libc.protocol_conformsToProtocol(ffi.cast("Protocol *", subclass.cdata), ffi.cast("Protocol *", self.cdata)):
				return True
			
			# See if any of the protocols directly adopted by subclass conform (directly or indirectly) to self.
			for proto in subclass.protocols:
				if issubclass(proto, self):
					return True
			
			return False
		else:
			raise TypeError("Argument 1 of issubclass(arg, {cls.__module__}.{cls.__qualname__}()) must be an objc.Class or objc.Protocol, not {tp.__module__}.{tp.__qualname__}".format(cls=type(self), tp=type(subclass)))
	
	def __instancecheck__(self, instance):
		if isinstance(instance, ID):
			if instance.cls.instances_respond_to_api("conformsToProtocol:"):
				return bool(instance.msg_send("conformsToProtocol:", self))
			else:
				return issubclass(instance.cls, self)
		else:
			return False

class Block(ID):
	__slots__ = ("_descriptor", "_func", "_literal")
	
	def __new__(cls, func):
		descriptor = ffi.new("struct Block_descriptor_1 *")
		descriptor.reserved = 0
		descriptor.size = ffi.sizeof("struct Block_literal_1")
		descriptor.copy_helper = None
		descriptor.dispose_helper = None
		descriptor.signature = None
		
		literal = ffi.new("struct Block_literal_1 *")
		literal.isa = ffi.cast("Class", classes.__NSGlobalBlock__.cdata)
		literal.flags = libc.BLOCK_IS_GLOBAL
		literal.reserved = 0
		literal.invoke = ffi.cast("uncast_polymorphic_return (*)(id self, uncast_polymorphic_arguments args)", func)
		literal.descriptor = descriptor
		
		self = super().__new__(ffi.cast("id", literal))
		object.__setattr__(self, "_descriptor", descriptor)
		object.__setattr__(self, "_func", func)
		object.__setattr__(self, "_literal", literal)
		return self

