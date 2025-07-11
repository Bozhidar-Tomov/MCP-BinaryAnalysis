#include <stdio.h>

int main() {
    // Variable declarations
    int num1, num2;
    int sum, difference, product;
    float quotient;
    
    // Display program title
    printf("=== Simple Calculator Program ===\n");
    
    // Get input from user
    printf("Enter the first number: ");
    scanf("%d", &num1);
    
    printf("Enter the second number: ");
    scanf("%d", &num2);
    
    // Perform calculations
    sum = num1 + num2;
    difference = num1 - num2;
    product = num1 * num2;
    
    // Check for division by zero
    if (num2 != 0) {
        quotient = (float)num1 / num2;
    }
    
    // Display results
    printf("\n=== Results ===\n");
    printf("Addition: %d + %d = %d\n", num1, num2, sum);
    printf("Subtraction: %d - %d = %d\n", num1, num2, difference);
    printf("Multiplication: %d × %d = %d\n", num1, num2, product);
    
    if (num2 != 0) {
        printf("Division: %d ÷ %d = %.2f\n", num1, num2, quotient);
    } else {
        printf("Division: Cannot divide by zero!\n");
    }
    
    return 0;
}