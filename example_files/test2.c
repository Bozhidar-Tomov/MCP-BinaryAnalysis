#include <stdio.h>

int main() {
    int num1, num2;
    int sum, difference, product;
    float division;
    
    // Print prompts and read input
    printf("Enter first number: ");
    scanf("%d", &num1);
    
    printf("Enter second number: ");
    scanf("%d", &num2);
    
    // Perform calculations
    sum = num1 + num2;
    difference = num1 - num2;
    product = num1 * num2;
    
    // Division (only if num2 is not zero)
    if (num2 != 0) {
        division = (float)num1 / (float)num2;
    }
    
    // Print results
    printf("\nResults:\n");
    printf("%d + %d = %d\n", num1, num2, sum);
    printf("%d - %d = %d\n", num1, num2, difference);
    printf("%d * %d = %d\n", num1, num2, product);
    
    if (num2 != 0) {
        printf("%d / %d = %.2f\n", num1, num2, division);
    } else {
        printf("Division by zero is undefined\n");
    }
    
    return 0;
}