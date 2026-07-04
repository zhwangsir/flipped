import { describe, it, expect } from 'vitest';
import { formatTokens } from './format';

describe('formatTokens', () => {
  it('0 与小值原样', () => {
    expect(formatTokens(0)).toBe('0');
    expect(formatTokens(999)).toBe('999');
  });
  it('整千 → 1.0k', () => expect(formatTokens(1000)).toBe('1.0k'));
  it('千级一位小数', () => expect(formatTokens(12345)).toBe('12.3k'));
  it('百万 → M', () => expect(formatTokens(1234567)).toBe('1.2M'));
});
