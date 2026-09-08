# How to use this file with Copilot
- In Copilot Chat, say: “Apply all rules from this file to my code.”
- Or: “Write code using the conventions in this file.”

# Coding Conventions Prompts (Copilot-Optimized)

- Use template literals (`${}`) for all string concatenation.
- Do not use console.log or leave debug code.
- Remove unused and commented-out code.
- Write comments only for adjacent code.
- Do not comment out removed code; use source control.
- All new/changed functions must have unit tests (see PROMPT_unit_test.md).
- Avoid performance issues and repetitive code.
- Prefer switch or object mapping over repetitive if/else.
- Use arrow functions for callbacks.
- Use camelCase for variables; append $ for observables.
- Use public for variables accessed outside a component, private for internal.
- Use JSDoc comments for all methods.
- Format `} else {` on the same line.
- Use unique, hyphen-separated ids for HTML elements with content.
- Tab size must be 4.
- Do not disable any ESLint rules.
- Use optional chaining (`?.`) instead of `&&` for property access.

# Example: String Concatenation
```
const greeting = `${hi} ${name}`;
```

# Example: Variable Naming
```
const myValue = 1;
const myObservable$ = new BehaviorSubject(true);
```

# Example: Method JSDoc
```
/**
 * Adds two numbers
 * @param a: number - first number
 * @param b: number - second number
 * @returns number - sum
 */
add(a: number, b: number): number {
    return a + b;
}
```
 
# Example: Optional Chaining
```
// ✅ Preferred
const email = user?.profile?.email;

// ❌ Not Allowed
const email = user && user.profile && user.profile.email;
```

# Example: Method Definition and JSDoc
```
/**
 * Definition of method
 * @param firstArgument: string - definition of variable
 * @param secondArgument: number - definition of variable
 * @param thirdArgument: boolean - definition of variable
 * Definition of what method returns (when applicable)
 */
exampleMethod(firstArgument: string, secondArgument: number, thirdArgument: boolean) {
    return new Promise((resolve, reject) => {
        if (firstArgument) {
            // Code
            resolve(thirdArgument);
        } else { // Ensure } else { is formatted as such. Do not drop else to new line
            // Code
            reject(false);
        }
    });
}
```
