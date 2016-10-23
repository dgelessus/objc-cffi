# `objc-cffi`

A CFFI-based library for accessing the Objective-C runtime. This library is meant for use in [Pythonista](http://omz-software.com/pythonista/) and requires Python 3.5 and CFFI 1.8 or later.

## Features

* Calling methods on Objective-C classes and objects using Python method call syntax
* Getting and setting Objective-C properties using Python attribute syntax
* Checking types of Objective-C objects using `isinstance` and `issubclass`
* Easy use of Objective-C classes and protocols using the `objc.classes` and `objc.protocols` pseudo-modules
* Automatic deduction of method signatures and property types from type encodings
* Automatic conversion of Python to Objective-C objects when passed to methods
* Conversion from and to most `objc_util` objects
* Hiding of private and known deprecated methods in `dir` lists, for clean autocompletion in the interactive Python console
* Access to class, protocol, method, property, and ivar metadata

## Issues and missing features

* Subscript syntax for Objective-C collections
* Python iteration support for Objective-C collections and fast enumerations
* Creation of custom Objective-C classes at runtime
* Better `struct` support (methods taking or returning `struct`s currently require manual setting of `restype` or `argtypes` to be properly usable)
* Performance optimizations (this library is quite slow compared to `objc_util`)

