package android.util; public abstract class FloatProperty<T> { public FloatProperty(String n) {} public abstract void setValue(T object, float value); public abstract Float get(T object); }
