from . import api

__all__ = []

#--- objc/NSObjCRuntime.h
api.ffi.cdef("""
typedef long NSInteger;
typedef unsigned long NSUInteger;
""")

api.ffi.cdef("""
#define NSIntegerMax {NSIntegerMax}L
#define NSIntegerMin {NSIntegerMin}L
#define NSUIntegerMax {NSUIntegerMax}L
""".format(
	NSIntegerMax=2**(8*api.ffi.sizeof("NSInteger")-1) - 1,
	NSIntegerMin=-2**(8*api.ffi.sizeof("NSInteger")-1),
	NSUIntegerMax=2**(8*api.ffi.sizeof("NSUInteger")) - 1,
))

#--- Foundation/NSObjCRuntime.h
api.ffi.cdef("""
typedef id_s NSObject;
typedef NSObject NSString;

extern NSString *NSStringFromSelector(SEL aSelector);
extern SEL NSSelectorFromString(NSString *aSelectorName);

extern NSString *NSStringFromClass(Class aClass);
extern Class NSClassFromString(NSString *aClassName);

extern NSString *NSStringFromProtocol(Protocol *proto);
extern Protocol *NSProtocolFromString(NSString *namestr);

extern const char *NSGetSizeAndAlignment(const char *typePtr, NSUInteger *sizep, NSUInteger *alignp);

extern void NSLog(NSString *format, ...);
extern void NSLogv(NSString *format, va_list args);

typedef NSInteger NSComparisonResult;
enum {
	NSOrderedAscending = -1,
	NSOrderedSame = 0,
	NSOrderedDescending = 1,
};

//typedef NSComparisonResult (^NSComparator)(id obj1, id obj2);
typedef NSBlock NSComparator;

typedef NSUInteger NSEnumerationOptions;
enum {
	NSEnumerationConcurrent = 0x1, // (1UL << 0),
	NSEnumerationReverse = 0x2, // (1UL << 1),
};

typedef NSUInteger NSSortOptions;
enum {
	NSSortConcurrent = 0x1, // (1UL << 0),
	NSSortStable = 0x10, // (1UL << 4),
};

typedef NSInteger NSQualityOfService;
enum {
	NSQualityOfServiceUserInteractive = 0x21,
	NSQualityOfServiceUserInitiated = 0x19,
	NSQualityOfServiceUtility = 0x11,
	NSQualityOfServiceBackground = 0x09,
	NSQualityOfServiceDefault = -1,
};

#define YES 1
#define NO 0
""")

api.ffi.cdef("""
//static const NSInteger NSNotFound = NSIntegerMax;
#define NSNotFound {api.libc.NSIntegerMax}
""".format(api=api))

#--- Foundation/NSZone.h
api.ffi.cdef("""
typedef struct _NSZone NSZone;
""")

#--- Foundation/NSEnumerator.h
api.ffi.cdef("""
typedef struct {
	unsigned long state;
	id *itemsPtr;
	unsigned long *mutationsPtr;
	unsigned long extra[5];
} NSFastEnumerationState;
""")

#--- Foundation/NSRange.h
api.ffi.cdef("""
typedef struct _NSRange {
	NSUInteger location;
	NSUInteger length;
} NSRange;

typedef NSRange *NSRangePointer;

extern NSRange NSUnionRange(NSRange range1, NSRange range2);
extern NSRange NSIntersectionRange(NSRange range1, NSRange range2);
extern NSString *NSStringFromRange(NSRange range);
extern NSRange NSRangeFromString(NSString *aString);
""")

#--- Foundation/NSData.h
api.ffi.cdef("""
typedef NSUInteger NSDataReadingOptions;
enum {
	NSDataReadingMappedIfSafe = 0x1, // 1UL << 0,
	NSDataReadingUncached = 0x2, // 1UL << 1,
	NSDataReadingMappedAlways = 0x4, // 1UL << 3,
};

typedef NSUInteger NSDataWritingOptions;
enum {
	NSDataWritingAtomic = 0x1, // 1UL << 0,
	NSDataWritingWithoutOverwriting = 0x2, // 1UL << 1,
	NSDataWritingFileProtectionNone = 0x10000000,
	NSDataWritingFileProtectionComplete = 0x20000000,
	NSDataWritingFileProtectionCompleteUnlessOpen = 0x30000000,
	NSDataWritingFileProtectionCompleteUntilFirstUserAuthentication = 0x40000000,
	NSDataWritingFileProtectionMask = 0xf0000000,
};


typedef NSUInteger NSDataSearchOptions;
enum {
	NSDataSearchBackwards = 0x1, // 1UL << 0,
	NSDataSearchAnchored = 0x2, // 1UL << 1,
};

typedef NSUInteger NSDataBase64EncodingOptions;
enum {
	NSDataBase64Encoding64CharacterLineLength = 0x1, // 1UL << 0,
	NSDataBase64Encoding76CharacterLineLength = 0x2, // 1UL << 1,
	NSDataBase64EncodingEndLineWithCarriageReturn = 0x10, // 1UL << 4,
	NSDataBase64EncodingEndLineWithLineFeed = 0x20, // 1UL << 5,
};

typedef NSUInteger NSDataBase64DecodingOptions;
enum {
	NSDataBase64DecodingIgnoreUnknownCharacters = 0x1, // 1UL << 0,
};
""")

#--- Foundation/NSError.h
api.ffi.cdef("""
extern NSString */*const*/ NSCocoaErrorDomain;

extern NSString */*const*/ NSPOSIXErrorDomain;
extern NSString */*const*/ NSOSStatusErrorDomain;
extern NSString */*const*/ NSMachErrorDomain;

extern NSString */*const*/ NSUnderlyingErrorKey;

extern NSString */*const*/ NSLocalizedDescriptionKey;
extern NSString */*const*/ NSLocalizedFailureReasonErrorKey;
extern NSString */*const*/ NSLocalizedRecoverySuggestionErrorKey;
extern NSString */*const*/ NSLocalizedRecoveryOptionsErrorKey;
extern NSString */*const*/ NSRecoveryAttempterErrorKey;
extern NSString */*const*/ NSHelpAnchorErrorKey;

extern NSString */*const*/ NSStringEncodingErrorKey;
extern NSString */*const*/ NSURLErrorKey;
extern NSString */*const*/ NSFilePathErrorKey;
""")

#--- Foundation/NSString.h
api.ffi.cdef("""
typedef unsigned short unichar;

typedef NSUInteger NSStringCompareOptions;
enum {
	NSCaseInsensitiveSearch = 1,
	NSLiteralSearch = 2,
	NSBackwardsSearch = 4,
	NSAnchoredSearch = 8,
	NSNumericSearch = 64,
	NSDiacriticInsensitiveSearch = 128,
	NSWidthInsensitiveSearch = 256,
	NSForcedOrderingSearch = 512,
	NSRegularExpressionSearch = 1024,
};

typedef NSUInteger NSStringEncoding;
enum NSStringEncoding {
	NSASCIIStringEncoding = 1,
	NSNEXTSTEPStringEncoding = 2,
	NSJapaneseEUCStringEncoding = 3,
	NSUTF8StringEncoding = 4,
	NSISOLatin1StringEncoding = 5,
	NSSymbolStringEncoding = 6,
	NSNonLossyASCIIStringEncoding = 7,
	NSShiftJISStringEncoding = 8,
	NSISOLatin2StringEncoding = 9,
	NSUnicodeStringEncoding = 10,
	NSWindowsCP1251StringEncoding = 11,
	NSWindowsCP1252StringEncoding = 12,
	NSWindowsCP1253StringEncoding = 13,
	NSWindowsCP1254StringEncoding = 14,
	NSWindowsCP1250StringEncoding = 15,
	NSISO2022JPStringEncoding = 21,
	NSMacOSRomanStringEncoding = 30,
	
	//NSUTF16StringEncoding = NSUnicodeStringEncoding,
	NSUTF16StringEncoding = 10,
	
	NSUTF16BigEndianStringEncoding = 0x90000100,
	NSUTF16LittleEndianStringEncoding = 0x94000100,
	
	NSUTF32StringEncoding = 0x8c000100,                   
	NSUTF32BigEndianStringEncoding = 0x98000100,
	NSUTF32LittleEndianStringEncoding = 0x9c000100,
	
	NSProprietaryStringEncoding = 65536,
};

typedef NSUInteger NSStringEncodingConversionOptions;
enum {
	NSStringEncodingConversionAllowLossy = 1,
	NSStringEncodingConversionExternalRepresentation = 2,
};

extern NSString * /*const*/ NSStringTransformLatinToKatakana;
extern NSString * /*const*/ NSStringTransformLatinToHiragana;
extern NSString * /*const*/ NSStringTransformLatinToHangul;
extern NSString * /*const*/ NSStringTransformLatinToArabic;
extern NSString * /*const*/ NSStringTransformLatinToHebrew;
extern NSString * /*const*/ NSStringTransformLatinToThai;
extern NSString * /*const*/ NSStringTransformLatinToCyrillic;
extern NSString * /*const*/ NSStringTransformLatinToGreek;
extern NSString * /*const*/ NSStringTransformToLatin;
extern NSString * /*const*/ NSStringTransformMandarinToLatin;
extern NSString * /*const*/ NSStringTransformHiraganaToKatakana;
extern NSString * /*const*/ NSStringTransformFullwidthToHalfwidth;
extern NSString * /*const*/ NSStringTransformToXMLHex;
extern NSString * /*const*/ NSStringTransformToUnicodeName;
extern NSString * /*const*/ NSStringTransformStripCombiningMarks;
extern NSString * /*const*/ NSStringTransformStripDiacritics;

extern NSString * /*const*/ NSStringEncodingDetectionSuggestedEncodingsKey;
extern NSString * /*const*/ NSStringEncodingDetectionDisallowedEncodingsKey;
extern NSString * /*const*/ NSStringEncodingDetectionUseOnlySuggestedEncodingsKey;
extern NSString * /*const*/ NSStringEncodingDetectionAllowLossyKey;
extern NSString * /*const*/ NSStringEncodingDetectionFromWindowsKey;
extern NSString * /*const*/ NSStringEncodingDetectionLossySubstitutionKey;
extern NSString * /*const*/ NSStringEncodingDetectionLikelyLanguageKey;

extern NSString * /*const*/ NSCharacterConversionException;
extern NSString * /*const*/ NSParseErrorException;
""")

api.ffi.cdef("""
//#define NSMaximumStringLength (INT_MAX-1)
#define NSMaximumStringLength {}
""".format((2**(8*api.ffi.sizeof("int")) - 1) - 1))

#--- Known classes and protocols
# Access some classes to add them to the list of known classes

api.protocols.NSCoding
api.protocols.NSCopying
api.protocols.NSDiscardableContent
api.protocols.NSFastEnumeration
api.protocols.NSMutableCopying
api.protocols.NSObject
api.protocols.NSSecureCoding

api.classes.__NSGlobalBlock
api.classes.__NSGlobalBlock__
api.classes.__NSStackBlock
api.classes.__NSStackBlock__
api.classes.NSArray
api.classes.NSBlock
api.classes.NSCountedSet
api.classes.NSData
api.classes.NSDictionary
api.classes.NSEnumerator
api.classes.NSError
api.classes.NSMutableArray
api.classes.NSMutableData
api.classes.NSMutableDictionary
api.classes.NSMutableSet
api.classes.NSMutableString
api.classes.NSNumber
api.classes.NSNull
api.classes.NSObject
api.classes.NSSet
api.classes.NSString
api.classes.NSValue

