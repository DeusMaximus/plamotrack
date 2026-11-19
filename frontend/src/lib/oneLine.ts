/** A line break, as a one-line box would lose it (#361). An `<input>` strips
 *  every CR and LF from a value it is given (the HTML value sanitisation for
 *  text), so these are the two characters, and CRLF is one break, not two. */
const LINE_BREAK = /\r\n|[\r\n]/g;

/** `value` as a one-line box can show it: each line break a space, so the two
 *  words a break separated stay two words. */
export function oneLine(value: string): string {
  return value.replace(LINE_BREAK, " ");
}
