//! Fixed-score lists with measured capacities; no per-frame heap allocation.
use core::{mem::MaybeUninit, ops::Deref};

#[derive(Debug)]
pub struct Fixed<T: Copy, const N: usize> { items: [MaybeUninit<T>; N], len: usize }
impl<T: Copy, const N: usize> FromIterator<T> for Fixed<T, N> {
    fn from_iter<I: IntoIterator<Item = T>>(items: I) -> Self {
        let mut result = Self { items: [MaybeUninit::uninit(); N], len: 0 };
        // Capacities are measured maxima of the fixed timeline (never exceeded).
        for item in items { unsafe { result.items.as_mut_ptr().add(result.len).write(MaybeUninit::new(item)); } result.len += 1; }
        result
    }
}
impl<T: Copy, const N: usize> Deref for Fixed<T, N> {
    type Target = [T];
    fn deref(&self) -> &[T] {
        // Only the initialized prefix is exposed; T is Copy and has no destructor.
        unsafe { core::slice::from_raw_parts(self.items.as_ptr().cast(), self.len) }
    }
}
impl<T: Copy, const N: usize> IntoIterator for Fixed<T, N> {
    type Item = T;
    type IntoIter = core::iter::Map<core::iter::Take<core::array::IntoIter<MaybeUninit<T>, N>>, fn(MaybeUninit<T>) -> T>;
    fn into_iter(self) -> Self::IntoIter {
        fn initialized<T>(item: MaybeUninit<T>) -> T { unsafe { item.assume_init() } }
        self.items.into_iter().take(self.len).map(initialized::<T>)
    }
}
impl<'a, T: Copy, const N: usize> IntoIterator for &'a Fixed<T, N> {
    type Item = &'a T;
    type IntoIter = core::slice::Iter<'a, T>;
    fn into_iter(self) -> Self::IntoIter { self.iter() }
}
