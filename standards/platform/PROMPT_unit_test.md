# How to use this file with Copilot
- In Copilot Chat, say: “Write unit tests using the format in this file.”
- Or: “Apply all test conventions from this file to my code.”

# Unit Test Prompt (Copilot-Optimized)

- Use a test case array structure for all unit tests.
- Cover valid, invalid, and edge case inputs.
- Use descriptive test case names and clear setup/expectation functions.
- No commented-out or unused test code.
- All new/changed functions must have corresponding tests.
- Follow all naming, formatting, and code reuse conventions.

# Example Structure
```
const myFunctionTestCases = [
    {
        description: 'should ...',
        setup: () => ({ input: '...', expected: '...' }),
        expectations: (result, expected) => { expect(result).toBe(expected); }
    }
];
myFunctionTestCases.forEach(({ description, setup, expectations }) => {
    it(description, () => {
        const { input, expected } = setup();
        const result = myFunction(input);
        expectations(result, expected);
    });
});
```
