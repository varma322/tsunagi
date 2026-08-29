# R8 configuration for the release build.
#
# Most of what this app needs is already covered by rules the libraries ship
# with themselves, which is worth recording so nobody re-adds them by hand:
#
#   Retrofit 3          META-INF/proguard/retrofit2.pro -- keeps annotated
#                       interfaces and the generic signatures its converters
#                       reflect over.
#   kotlinx.serialization
#                       META-INF/com.android.tools/r8/*.pro -- keeps the
#                       generated $$serializer for every @Serializable class.
#   Room, OkHttp        proguard.txt in each AAR.
#   WorkManager         keeps ListenableWorker subclasses by name, along with
#                       the (Context, WorkerParameters) constructor it calls
#                       reflectively -- which is how SyncWorker is started.
#
# Anything below is this project's own.

# Crash reports from a minified build are unreadable without these. The line
# numbers cost a little size and are what makes a stack trace from a phone
# worth having at all; renaming the source file back hides the obfuscated name.
-keepattributes SourceFile,LineNumberTable
-renamesourcefileattribute SourceFile

# Retrofit reads a suspend function's return type from the generic signature of
# the Continuation it is compiled into -- the JVM return type of every suspend
# function is just Object. R8 rewrites that signature to Object when the type
# argument is a class nothing else keeps, which is any response the app does not
# read: the check-in is issued for its effect, not its body. The call then fails
# with "Unable to create converter for class java.lang.Object" at the first
# request, in the release build only, on a device.
#
# Retrofit's own rules do not reach this. Theirs keep the declared return type,
# which for a suspend function is Object, and keeping kotlin.coroutines.
# Continuation preserves the signature without preserving what it refers to.
#
# Kept as a package rule rather than naming the responses that happen to be
# unread today: the next one added would fail the same way, in the field.
-keep,allowobfuscation class com.vce.tsunagi.data.remote.** { *; }
