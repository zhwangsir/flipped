import { afterEach, beforeEach, describe, it, expect } from 'vitest';
import { renderHook, act, cleanup } from '@testing-library/react';
import { useTheme } from './useTheme';

const STORAGE_KEY = 'flipped-theme';

afterEach(() => {
  cleanup();
  localStorage.clear();
  document.documentElement.removeAttribute('data-theme');
});

beforeEach(() => {
  localStorage.clear();
  document.documentElement.removeAttribute('data-theme');
});

describe('useTheme', () => {
  it('默认读取 data-theme=light 时返回 light', () => {
    document.documentElement.setAttribute('data-theme', 'light');
    const { result } = renderHook(() => useTheme());
    expect(result.current.theme).toBe('light');
  });

  it('data-theme=dark 时返回 dark', () => {
    document.documentElement.setAttribute('data-theme', 'dark');
    const { result } = renderHook(() => useTheme());
    expect(result.current.theme).toBe('dark');
  });

  it('无 data-theme 时默认 light', () => {
    const { result } = renderHook(() => useTheme());
    expect(result.current.theme).toBe('light');
  });

  it('toggle: light → dark', () => {
    document.documentElement.setAttribute('data-theme', 'light');
    const { result } = renderHook(() => useTheme());
    act(() => result.current.toggle());
    expect(result.current.theme).toBe('dark');
  });

  it('toggle: dark → light', () => {
    document.documentElement.setAttribute('data-theme', 'dark');
    const { result } = renderHook(() => useTheme());
    act(() => result.current.toggle());
    expect(result.current.theme).toBe('light');
  });

  it('theme 变化时同步到 documentElement data-theme', () => {
    document.documentElement.setAttribute('data-theme', 'light');
    const { result } = renderHook(() => useTheme());
    act(() => result.current.toggle());
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
  });

  it('theme 变化时同步到 localStorage', () => {
    document.documentElement.setAttribute('data-theme', 'light');
    const { result } = renderHook(() => useTheme());
    act(() => result.current.toggle());
    expect(localStorage.getItem(STORAGE_KEY)).toBe('dark');
  });

  it('多次 toggle 来回切换', () => {
    document.documentElement.setAttribute('data-theme', 'light');
    const { result } = renderHook(() => useTheme());
    act(() => result.current.toggle());
    expect(result.current.theme).toBe('dark');
    act(() => result.current.toggle());
    expect(result.current.theme).toBe('light');
    act(() => result.current.toggle());
    expect(result.current.theme).toBe('dark');
  });

  it('toggle 引用稳定(useCallback)', () => {
    const { result, rerender } = renderHook(() => useTheme());
    const first = result.current.toggle;
    rerender();
    expect(result.current.toggle).toBe(first);
  });
});
