## String Concatenation
```
    const hi = 'Hello';
    const name = 'you';

    const preferredMethod = `${hi} ${name}`;
    const incorrectMethod = hi + ' ' + name; 
```

- In the example above it is preferred to use the interpolation `${}` syntax

## JavaScript Guidelines
These guidelines should be considered when reviewing JavaScript code.

* No use of console logging to stdout
* Unused code should be removed
* Code comments should be helpful with respect to code locality. That is, comments should concern the code adjacent to their respective lines.
* Code that is removed should not be left as comments. Instead use source control for tracking removed code.
* Include unit tests for new functionality or if a function is modified and doesn't have a unit test
* Review for performance issues
* Review definition of endpoints and apply proper resource separation
* Follow standard naming conventions
* IDE tab size should be set to 4
* Ensure that you have ESLint installed and enabled
* Do not disable any linting rules
* Avoid using repetitive if else (use switch case instead) or object mapping (when applicable)
* Reuse code as much as posssible and remove unnecessary code
* Use arrow function over anonymous function expressions

## ❌ Do Not Use `async/await` in Frontend Code
We do **not** use `async/await` in frontend (Angular) code. All Promises should be handled using `.then()` and `.catch()` for consistency across the codebase.

```ts
// ✅ Preferred
someServiceCall().then(result => {
    // handle result
}).catch(error => {
    // handle error
});

// ❌ Not Allowed
const result = await someServiceCall();
```

## ❌ Do Not Use `hasOwnProperty`
We do not use `hasOwnProperty()` directly on objects. Instead, use the safe navigation operator (?.) or proper object structure validation.
```
// ✅ Preferred
if (config?.settings?.enabled) {
    // logic here
}

// ❌ Not Allowed
if (config.hasOwnProperty('settings')) {
    // logic here
}
```

## ✅ Use the Safe Navigation Operator `?.`
Always use the safe navigation operator `?.` to safely access nested object properties and avoid runtime errors caused by null or undefined.
```
// ✅ Preferred
const email = user?.profile?.email;

// ❌ Not Allowed
const email = user && user.profile && user.profile.email;
```

## Variable Naming Convention

```
    const firstNumber = 1;
    let secondNumber = 2;
    const behaviorSubject$ = new BehaviorSubject<boolean>(true);

    public usedOutsideOfComponent = true;
    private usedStrictlyWithinComponent = true;
```

## Method Conventions

* Use the following structure for methods.
```
    /**
     * Definition of method
     * @param firstArgument: string - definition of variable
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

## When To Add an id For Cypress Testing
* ids should be unique and should be checked for within the project before being utilized
* Generally if an HTML element is going to have content you will need to add an id
* That would include buttons, dropdowns, inputs, lists, and any other elements that contain content
* Proper naming convention should use - to separate words ```id="example-of-id"```

## Unit Test Format
```
    const exampleFunctionTestCases = [
        {
            description: 'Should call exampleFunction and return the expected output',
            setup: () => {
                const input = "example input"; // replace with actual input
                const expectedOutput = "expected output"; // replace with expected output
                return { input, expectedOutput };
            },
            expectations: (result, expectedOutput) => {
                expect(result).toBe(expectedOutput);
            }
        },
        {
            description: 'Should throw an error for invalid input format',
            setup: () => {
                const input = 'invalid input'; // replace with invalid input
                return { input, expectedError: 'Invalid input format' }; // customize this message based on your implementation
            },
            expectations: (input, expectedError) => {
                expect(() => exampleFunction(input)).toThrowError(expectedError);
            }
        },
        {
            description: 'Should handle edge case with specific input',
            setup: () => {
                const input = 'edge case input'; // replace with edge case input
                const expectedOutput = 'expected edge case output'; // replace with expected output
                return { input, expectedOutput };
            },
            expectations: (result, expectedOutput) => {
                expect(result).toBe(expectedOutput);
            }
        }
    ];
    
    exampleFunctionTestCases.forEach(({ description, setup, expectations }) => {
        it(description, () => {
            const { input, expectedOutput, expectedError } = setup();
    
            // Call the function being tested
            const result = exampleFunction(input);
    
            // Check expectations
            if (expectedError) {
                expectations(input, expectedError);
            } else {
                expectations(result, expectedOutput);
            }
        });
    });
```
# Unit Test Expectations With Mock Data

This example demonstrates how to write test cases for a function that processes different types of data. The approach can be adapted for any nested data structure. 

The test cases are divided into two parts:

1. **Malformed Mock Data**: A loop that checks the handling of different types of `adtypePresets`(or other mocked data).
2. **Valid Mock Data With Nested Malformed Data**: Specifically for testing valid `adtypePresets` and their interactions with `spotJobPresets`, `spotUserPresets`, `spotFilePresets`, etc. The `if (presetKey === 'valid')` block is used for this nested data testing.

---

```
const getJobTestCases = Object.keys(adTypePresets).flatMap((presetKey) => {
    const adTypeMock = { ...adTypePresets[presetKey] };
    const testCases = [{
        description: `should handle the ${presetKey} adTypePreset correctly`,
        setup: () => {
            return { adTypeMock, jobMock: null };
        },
        expectations: (adTypeMock, _, result) => {
            if (!adTypeMock?.metadata?.jobs?.length) {
                expect(result).toBeNull();
                return;
            }
        }
    }];

    // Testing valid adType with its associated nested data, such as spotJobs, spotUsers, etc.
    if (presetKey === 'valid') {
        Object.keys(jobPresets).forEach((jobPresetKey) => {
            testCases.push({
                description: `should handle the ${presetKey} adTypePreset with ${jobPresetKey} jobPreset correctly`,
                setup: (): any => {
                    const jobMock = { ...jobPresets[jobPresetKey] };
                    adTypeMock.metadata.jobs = [];
                    adTypeMock.metadata.jobs[0] = jobMock;
                    return { adTypeMock, jobMock };
                },
                expectations: (_, jobMock, result) => {
                    if (!jobMock?.job_name) {
                        expect(result).toBeUndefined();
                        return;
                    }
                    expect(result).toEqual(jobMock.job_name === 'Writer' ? jobMock : undefined);
                }
            });
        });
    }

    return testCases;
});

getJobTestCases.forEach(({ description, setup, expectations }) => {
    it(description, () => {
        const { adTypeMock, jobMock } = setup();
        const result = component.getJob(adTypeMock);
        expectations(adTypeMock, jobMock, result);
    });
});
```

## Utilize the `| language_pipe` where applicable 

```
<!-- Correct usage: -->
<button type="button" (click)="someAction()" class="ui-button">
  <span class="ui-button-text">
    <i class="some-icon"></i>
    <span>{{ 'Button Label' | language_pipe }}</span>
  </span>
</button>

<!-- Inorrect usage: -->
<button type="button" (click)="someAction()" class="ui-button">
  <span class="ui-button-text">
    <i class="some-icon"></i>
    <span>Button Label</span><!-- ❌ Missing | language_pipe -->
  </span>
</button>
```