/**
 * frontend/src/lib/utils.ts — Utility functions for styling and component composition.
 */

export type ClassValue = string | number | boolean | undefined | null | { [key: string]: boolean | undefined | null };

/**
 * Combines CSS class names conditionally, following the shadcn/ui cn() utility pattern.
 */
export function cn(...inputs: ClassValue[]): string {
  const classes: string[] = [];

  for (const input of inputs) {
    if (!input) continue;

    if (typeof input === 'string' || typeof input === 'number') {
      classes.push(String(input));
    } else if (typeof input === 'object') {
      for (const [key, value] of Object.entries(input)) {
        if (value) {
          classes.push(key);
        }
      }
    }
  }

  return classes.join(' ');
}
