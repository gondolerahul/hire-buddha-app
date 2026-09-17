# kotlinx.serialization: keep generated serializers for @Serializable DTOs
-keepattributes *Annotation*, InnerClasses, Signature, Exceptions
-dontnote kotlinx.serialization.**
-keepclassmembers @kotlinx.serialization.Serializable class com.hirebuddha.dialer.** {
    *** Companion;
    kotlinx.serialization.KSerializer serializer(...);
}
-keepclasseswithmembers class com.hirebuddha.dialer.** {
    kotlinx.serialization.KSerializer serializer(...);
}

# Retrofit interfaces use suspend functions + generics
-keep,allowobfuscation,allowshrinking interface retrofit2.Call
-keep,allowobfuscation,allowshrinking class kotlin.coroutines.Continuation
-if interface * { @retrofit2.http.* <methods>; }
-keep,allowobfuscation interface <1>
