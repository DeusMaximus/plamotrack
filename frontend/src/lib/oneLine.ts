/** A line break, as a one-line box would lose it (#361). An `<input>` strips
 *  every CR and LF from a value it is given (the HTML value sanitisation for
 *  text), so these are the two characters, and CRLF is one break, not two. */
const LINE_BREAK = /\r\n|[\r\n]/g;

/** `value` as a one-line box can show it: each line break a space, so the two
 *  words a break separated stay two words. */
export function oneLine(value: string): string {
  return value.replace(LINE_BREAK, " ");
}

/** `value` as a `<textarea>` holds it (#376): each line break `\n`. A textarea's
 *  value normalises CRLF and a lone CR to LF, so a stored `\r\n` loaded into a
 *  form as it is would differ from its own box, and a box that was only
 *  clicked into would read to react-hook-form as an edit. A form's opening
 *  value for a textarea goes through this, and an untouched note is left as
 *  it is stored. */
export function asTextareaValue(value: string): string {
  return value.replace(LINE_BREAK, "\n");
}
