import { vi } from 'vitest';

/**
 * Replace `window.location` with a stand-in whose `reload` is a spy, for tests
 * of code that reloads the page.
 *
 * jsdom defines Location's members on the instance as unforgeable, so `reload`
 * can't be spied on in place; hence a stand-in carrying a copy of every member.
 * Each copy is BOUND to the real location: since jsdom 30.1 the accessors
 * brand-check `this`, so an unbound copy throws "'get search' called on an
 * object that is not a valid instance of Location" on its first read.
 */
export function stubLocationReload(): void {
  const real = window.location;
  const members: PropertyDescriptorMap = Object.getOwnPropertyDescriptors(real);
  for (const member of Object.values(members)) {
    if (member.get) member.get = member.get.bind(real);
    if (member.set) member.set = member.set.bind(real);
    const value: unknown = member.value;
    if (typeof value === 'function') member.value = value.bind(real);
  }
  vi.stubGlobal(
    'location',
    Object.defineProperties({}, { ...members, reload: { configurable: true, value: vi.fn() } }),
  );
}
