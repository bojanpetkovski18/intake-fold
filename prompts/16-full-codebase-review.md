# M16: Full-codebase review

**Branch:** `#0016-full-codebase-review`
**Goal:** every file reviewed, every confirmed issue fixed and tested, and a completion report.
**Context:** the owner's playbook, Phase 9. M15, the real-model run, stays owner-gated and is not needed first.

**How it fits the project rules**
- Scope is the whole codebase. "No unrelated refactors" yields to "fix every confirmed issue"; cosmetic churn and new features stay out.
- `docs/REVIEW.md` is the coverage checklist and the findings log, committed as the review goes.
- Every bug: the failing regression test first, shown failing for the right reason. Small commits, one root cause each.
- Ask the owner before any change to the spec, a public API contract, the schema beyond an additive migration, or anything destructive.
- Verification: the full gate on Windows and Linux, the e2e journey, a mutation check on each fix, and a real browser for any changed screen.
- The completion report goes in `docs/REVIEW.md`, and short in the chat, next to the milestone report and PR description.

## The owner's brief, word for word
```text
Act as a Senior Software Engineer, Software Architect, and QA Engineer with extensive experience in production-grade applications, clean architecture, debugging, performance optimization, security, and maintainability.

Your task is to perform a complete, thorough, end-to-end review of the entire codebase, starting from the very beginning of the project and covering every file, component, module, feature, dependency, and integration.

Your objective is not simply to identify issues or provide recommendations. You must investigate, fix, validate, and resolve every legitimate bug and issue you discover.

1. Thoroughly Review the Entire Codebase

Start by understanding the project from its foundation.

Review the complete project structure.

Understand the architecture, design patterns, and overall application flow.

Inspect every relevant source file, configuration file, component, service, handler, controller, model, repository, utility, and integration.

Review the code from the initial entry points through all dependent layers.

Understand how the frontend, backend, database, APIs, authentication, authorization, and external services interact.

Review existing documentation, requirements, comments, and implementation decisions.

Examine existing tests and identify missing or inadequate test coverage.

Identify duplicated logic, inconsistent implementations, technical debt, and architectural weaknesses.

Do not limit the review to recently modified files or obvious problem areas.

The entire codebase must be reviewed, not just the parts that appear to be broken.

2. Identify Every Potential Issue

Analyze the application as an experienced senior developer would.

Look for:

Functional Bugs

Incorrect business logic.

Incorrect calculations or data transformations.

Unexpected application behavior.

Broken workflows.

Incorrect conditions or branching logic.

Edge cases that are not handled.

Incorrect state management.

Null reference exceptions.

Race conditions and asynchronous execution issues.

Incorrect error handling.

Architecture and Code Quality

Violations of SOLID principles where they negatively affect the application.

Poor separation of concerns.

Incorrect abstraction boundaries.

Tight coupling.

Unnecessary complexity.

Duplicate code.

Inconsistent naming conventions.

Dead code and unused dependencies.

Incorrect design patterns.

Fragile implementations.

Performance

Inefficient database queries.

N+1 query problems.

Unnecessary API requests.

Memory leaks.

Excessive allocations.

Unnecessary rendering or processing.

Inefficient loops and algorithms.

Poor caching strategies.

Unnecessary background operations.

Scalability bottlenecks.

Security

Authentication and authorization vulnerabilities.

Improper input validation.

Injection vulnerabilities.

Sensitive data exposure.

Insecure configuration.

Incorrect permission checks.

Unsafe handling of user-provided data.

Dependency vulnerabilities.

Database and Data Integrity

Incorrect entity relationships.

Missing constraints or validations.

Incorrect migrations.

Data consistency problems.

Transaction handling issues.

Incorrect queries.

Potential data loss.

Schema inconsistencies.

Improper database access patterns.

Error Handling and Reliability

Unhandled exceptions.

Incorrect exception handling.

Missing logging.

Silent failures.

Incorrect fallback behavior.

Invalid retry mechanisms.

Unreliable external integrations.

Testing

Missing unit tests.

Missing integration tests.

Incorrect or flaky tests.

Tests that do not adequately validate behavior.

Missing edge-case coverage.

Regression risks.

3. Fix Every Confirmed Issue

After identifying an issue, do not stop at documenting it.

You must:

Determine the root cause.

Understand why the issue exists.

Implement the correct fix.

Ensure the fix does not introduce regressions.

Add or update automated tests where appropriate.

Validate the fix through execution and testing.

Fix all confirmed bugs and legitimate code quality, security, reliability, and performance issues that can be safely addressed.

Do not implement superficial workarounds when a proper root-cause fix is possible.

Do not leave TODOs, incomplete implementations, placeholder logic, or known bugs unresolved merely because they require additional investigation.

If a fix requires a broader architectural change, investigate the impact and implement it carefully rather than making an unsafe shortcut.

4. Preserve Existing Functionality

While making improvements:

Preserve all existing intended business behavior.

Do not remove working features.

Do not arbitrarily change APIs, contracts, database schemas, or public interfaces.

Maintain compatibility with existing consumers.

Follow the project's established architecture and coding conventions.

Avoid unnecessary refactoring.

Ensure that changes are backward-compatible unless a breaking change is explicitly justified and required.

Any potentially breaking change must be carefully evaluated before implementation.

5. Testing and Validation

After completing the fixes:

Build the entire solution.

Run all existing automated tests.

Add tests for newly fixed issues.

Run relevant integration tests.

Validate critical application workflows.

Check for compilation errors.

Check for runtime exceptions.

Validate database migrations and data access changes.

Check for regressions.

Verify that the application still behaves correctly.

Do not claim that a build or test passed unless you actually executed it and confirmed the result.

If a test cannot be executed due to environmental limitations, clearly explain the limitation and perform the strongest alternative validation available.

6. Review Your Own Changes

Once all identified issues have been addressed, perform a second independent review of your own modifications.

Ask yourself:

Is this fix actually correct?

Did I fix the root cause?

Could this change introduce a regression?

Is the implementation unnecessarily complicated?

Does it follow the existing architecture?

Are edge cases handled?

Is the code maintainable?

Are tests sufficient?

Are there any remaining issues in the surrounding code?

Then review the codebase again for issues that may have been missed during the initial pass.

7. Execution Strategy

Work systematically and autonomously.

Map the entire codebase.

Establish the current build and test baseline.

Review the project in logical modules and layers.

Track all identified issues.

Prioritize critical and high-severity issues first.

Fix issues systematically.

Add and execute tests.

Perform regression testing.

Conduct a final comprehensive review.

Produce a detailed completion report.

Do not stop after reviewing a few files.

Do not stop after finding the first bug.

Do not stop after fixing the most obvious problems.

Continue until every accessible and relevant part of the codebase has been reviewed and all actionable issues have been addressed.

If the codebase is too large to review in a single pass, break the work into manageable phases and maintain a clear checklist of reviewed files, discovered issues, completed fixes, and remaining work. Continue through each phase without losing track of coverage.

8. Important Rules

Do not merely provide suggestions. Implement the fixes.

Do not assume code is correct simply because it compiles.

Do not skip files without a justified reason.

Do not ignore edge cases.

Do not introduce unnecessary abstractions.

Do not sacrifice maintainability for quick fixes.

Do not disable tests to make the build pass.

Do not suppress warnings or exceptions without understanding their cause.

Do not modify unrelated files unnecessarily.

Do not make destructive database or production changes.

Do not expose secrets or sensitive information.

Do not claim completion while known actionable issues remain.

Be transparent about anything that cannot be verified.

Use your own senior-level engineering judgment throughout the process.

9. Final Completion Report

When the review is complete, provide a detailed report containing:

Executive Summary

Overall condition of the codebase and the most significant findings.

Codebase Coverage

Modules and layers reviewed.

Files or areas reviewed.

Areas that could not be reviewed and why.

Issues Found and Fixed

For each significant issue:

Severity.

File or component affected.

Root cause.

Description of the fix.

Tests added or updated.

Improvements

Summarize architectural, performance, security, reliability, and maintainability improvements.

Validation Results

Build status.

Unit test results.

Integration test results.

Regression test results.

Any remaining warnings or limitations.

Remaining Issues

List any unresolved issues, explaining why they remain unresolved and what is needed to address them.

Final Assessment

Provide an honest assessment of the codebase after the audit.

FINAL DIRECTIVE:

Approach this task as if you are the senior engineer responsible for the quality, stability, security, and long-term maintainability of a production application.

Be meticulous. Be critical. Be systematic.

Review the entire codebase from the beginning, understand every relevant part, fix every legitimate issue you find, validate your changes, and perform a final review.

The goal is to leave the codebase in the best possible production-ready state without compromising existing functionality.
```
