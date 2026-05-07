```markdown
## BMS Artifact Documentation: `COADM01.bms`

### 1. Executive Summary

The `COADM01.bms` BMS source file defines the screen layout for the CardDemo Admin Menu. This screen, identified by the business name "Admin Menu" and transaction ID `CA00`, supports the user task of managing Db2 transaction types. It presents a list of administrative options to the user, allowing selection of a specific function.

### 2. File and Mapset Context

The BMS source file is located at `carddemo\app\bms\COADM01.bms`. It defines a single mapset named `COADM01`. The DFHMSD controls for this mapset include `CTRL=(ALARM,FREEKB)`, `EXTATT=YES`, `LANG=COBOL`, `MODE=INOUT`, `STORAGE=AUTO`, and `TIOAPFX=YES`, with `TYPE=&&SYSPARM`. This mapset is associated with the COBOL program `COADM01C` and is invoked by the CICS transaction ID `CA00`. The header comments within the source file identify it as "CardDemo - Admin Menu Screen".

### 3. Map-by-Map Structure

The `COADM01.bms` file contains one map, `COADM1A`, which serves as the single screen for the Admin Menu.

*   **Map Name:** `COADM1A`
*   **Screen Name:** `COADM1A`
*   **Mapset:** `COADM01`
*   **Associated Program:** `COADM01C`
*   **Transaction ID:** `CA00`
*   **Total Fields:** 28
*   **Input Fields:** 1
*   **Output Fields:** 19
*   **Label Fields:** 8
*   **Screen Size:** 24 rows by 80 columns

#### Layout Observations

The screen layout for `COADM1A` is structured with a header, a central menu area, a user input prompt, and a footer.

*   **Header (Rows 1-2):** Displays transaction name (`TRNNAME`), program name (`PGMNAME`), current date (`CURDATE`), and current time (`CURTIME`), along with two title fields (`TITLE01`, `TITLE02`). Labels for "Tran:", "Prog:", "Date:", and "Time:" are present.
*   **Main Content (Rows 4-17):** A central title "Admin Menu" is displayed on row 4. The core of the screen is a list of 12 output fields (`OPTN001` through `OPTN012`) arranged vertically from row 6 to row 17, intended to display menu options.
*   **Input Area (Row 20):** A prompt "Please select an option :" is displayed, followed by a 2-character numeric input field named `OPTION`.
*   **Footer (Rows 23-24):** An error message field `ERRMSG` is located on row 23. Command key hints "ENTER=Continue F3=Exit" are displayed on row 24.

### 4. User Interaction Flow

Upon displaying the `COADM1A` screen, the user sees the Admin Menu title, current system information (transaction, program, date, time), and a list of available administrative options presented via the `OPTN` fields. The user is prompted to "Please select an option :". The user enters a numeric value into the `OPTION` field. Pressing the **ENTER** key (Continue) submits the selected option for processing by the `COADM01C` program. Pressing the **F3** key (Exit) indicates a request to exit the current screen or application flow. Any error messages resulting from user input or processing are displayed in the `ERRMSG` field.

### 5. Shared Field and Layout Patterns

*   **Header Information:** The top two rows consistently display system information:
    *   `_LABEL_1_1` (Tran:), `TRNNAME` (4 chars, BLUE)
    *   `_LABEL_2_1` (Prog:), `PGMNAME` (8 chars, BLUE)
    *   `_LABEL_1_65` (Date:), `CURDATE` (8 chars, BLUE, initial mm/dd/yy)
    *   `_LABEL_2_65` (Time:), `CURTIME` (8 chars, BLUE, initial hh:mm:ss)
    *   `TITLE01` (40 chars, YELLOW) and `TITLE02` (40 chars, YELLOW) are output fields for screen-specific titles.
*   **Menu Options:** A repeating pattern of 12 output fields, `OPTN001` through `OPTN012`, is used to display menu choices. Each `OPTN` field is 40 characters long, blue, and has `ASKIP,FSET,NORM` attributes. These fields are arranged vertically from row 6, column 20 to row 17, column 20.
*   **User Input:** The `OPTION` field is a 2-character numeric input field, located at row 20, column 41. It has attributes `FSET,IC,NORM,NUM,UNPROT`, indicating it is unprotected, numeric, and has the cursor initially placed there.
*   **Error Message:** The `ERRMSG` field is a prominent output field (78 characters, RED, BRT, FSET) at row 23, column 1, designated for displaying error or informational messages to the user.
*   **Command Key Hints:** A fixed label `_LABEL_24_1` at row 24, column 1, provides "ENTER=Continue F3=Exit" hints in YELLOW color.

### 6. Validation and Navigation Considerations

The `OPTION` input field requires validation to ensure the user enters a valid selection from the displayed menu. This validation logic is implemented within the associated COBOL program, `COADM01C`. The program is responsible for interpreting the numeric input, determining the next action or screen to display, and handling invalid entries by populating the `ERRMSG` field. Navigation from this screen is controlled by the `COADM01C` program based on the `OPTION` value or the **F3** command key. The program uses CICS `SEND` and `RECEIVE` commands to interact with this BMS map, sending data to populate output fields and receiving the user's input from the `OPTION` field.

### 7. Modernization Guidance

#### Modern UI Equivalent

A modern equivalent for the `COADM1A` screen would be a web page or mobile application screen featuring a list of clickable menu items (e.g., buttons, links, or a dropdown menu). Each `OPTN` field would correspond to a distinct menu item. The header information (transaction, program, date, time) would typically be displayed in a consistent header or footer component of the modern application.

#### API Boundary

The primary API boundary for this artifact is the selection made via the `OPTION` field. A modern API would expose an endpoint that accepts a parameter representing the selected administrative function. The `COADM01C` program's logic for processing the `OPTION` input and determining the subsequent action defines the core business logic that needs to be encapsulated by this API.

#### Migration Risks

*   **Menu Option Mapping:** The dynamic population of the `OPTN` fields by `COADM01C` needs careful consideration. The modern UI must accurately reflect the available options and map user selections back to the corresponding backend functions.
*   **Input Validation Logic:** The validation rules for the `OPTION` field (e.g., numeric, within a valid range) must be accurately re-implemented in the new application layer or API.
*   **Error Message Handling:** The `ERRMSG` field's usage for displaying feedback requires mapping to a modern error display mechanism (e.g., toast messages, inline validation errors, dedicated error areas).
*   **Navigation Flow:** The `COADM01C` program's logic for navigating to subsequent screens based on the selected `OPTION` needs to be fully understood and replicated in the modern application's routing and navigation.
```